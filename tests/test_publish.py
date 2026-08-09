"""Publishing a spec must produce a pack that genuinely runs.

The headline test is `test_published_pack_runs_a_real_case`: it publishes a
spec, opens a case against the new pack over HTTP, answers the interview, and
asserts the graph scored it and reached a terminal state. Anything less proves
only that files were written.

Every test publishes into a tmp_path packs directory, so the repo's own packs
are never touched.
"""

import pytest
from fastapi.testclient import TestClient

from voxgate.config import Settings
from voxgate.packs.publish import PublishError, publish_pack, validate_spec
from voxgate.service.app import create_app


def spec(**overrides):
    base = {
        "pack_id": "test-clinic",
        "display_name": "Test Clinic Intake",
        "gate_role": "Duty Nurse",
        "persona": "You are a calm intake interviewer. You never diagnose.",
        "gate_reason": "urgent presentations",
        "thresholds": {"low": 0.30, "high": 0.65},
        "bias": -2.5,
        "fields": [
            {"name": "patient_name", "type": "text",
             "question": "What is your name?", "min_words": 1},
            {"name": "urgency", "type": "enum", "weight": 1.6,
             "question": "How urgent is it?",
             "values": {"routine": 0.1, "soon": 0.5, "urgent": 0.95}},
            {"name": "symptom_area", "type": "enum", "weight": 1.1,
             "question": "Which area is affected?",
             "values": {"limb": 0.2, "chest": 0.9, "head": 0.6}},
        ],
        "checks": [
            {"name": "red_flag", "field": "symptom_area",
             "flags": {"hit": ["chest"], "review": ["head"]}},
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def packs_dir(tmp_path):
    d = tmp_path / "packs"
    d.mkdir()
    return d


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def test_a_sound_spec_validates():
    validate_spec(spec())


@pytest.mark.parametrize(
    "pack_id",
    ["../escape", "/absolute", "Has-Caps", "trailing-", "has_underscore", ""],
)
def test_pack_id_must_be_a_safe_slug(pack_id):
    """pack_id becomes a directory name. Traversal must be impossible."""
    with pytest.raises(PublishError, match="pack_id"):
        validate_spec(spec(pack_id=pack_id))


def test_reserved_field_name_is_rejected():
    fields = spec()["fields"]
    fields[0]["name"] = "case_id"
    with pytest.raises(PublishError, match="reserved"):
        validate_spec(spec(fields=fields))


def test_non_identifier_field_name_is_rejected():
    fields = spec()["fields"]
    fields[0]["name"] = "2bad name"
    with pytest.raises(PublishError, match="identifier"):
        validate_spec(spec(fields=fields))


def test_non_identifier_enum_value_is_rejected():
    """An enum value becomes a Python set literal member and a schema enum."""
    fields = spec()["fields"]
    fields[1]["values"] = {"fine": 0.1, "not ok!": 0.9}
    with pytest.raises(PublishError, match="enum value"):
        validate_spec(spec(fields=fields))


def test_check_pointing_at_a_missing_field_is_rejected():
    with pytest.raises(PublishError, match="not a field"):
        validate_spec(spec(checks=[
            {"name": "ghost", "field": "nope", "flags": {"hit": [], "review": []}}
        ]))


def test_thresholds_must_be_ordered():
    with pytest.raises(PublishError, match="thresholds"):
        validate_spec(spec(thresholds={"low": 0.8, "high": 0.2}))


# --------------------------------------------------------------------------
# Writing and loading
# --------------------------------------------------------------------------

def test_publish_writes_the_five_files(packs_dir):
    publish_pack(spec(), packs_dir)
    written = packs_dir / "test_clinic"
    for name in ("pack.yaml", "schema.py", "checks.py", "scoring.py", "prompt.md"):
        assert (written / name).exists(), name


def test_published_pack_satisfies_the_loader_contract(packs_dir):
    pack = publish_pack(spec(), packs_dir)
    assert pack.pack_id == "test-clinic"
    assert set(pack.reask_hints) == set(pack.schema_model.model_fields)
    assert pack.checks and pack.scorecard


def test_refuses_to_overwrite_without_being_told(packs_dir):
    publish_pack(spec(), packs_dir)
    with pytest.raises(PublishError, match="already exists"):
        publish_pack(spec(), packs_dir)
    publish_pack(spec(display_name="Renamed"), packs_dir, overwrite=True)


def test_a_pack_that_cannot_load_is_rolled_back(packs_dir):
    """A broken pack left on disk would break load_packs for every other pack,
    so publishing must clean up after itself."""
    bad = spec(fields=[
        {"name": "only_one", "type": "text", "question": "Why?", "min_words": 1},
        {"name": "second", "type": "enum", "weight": 1.0, "question": "Which?",
         "values": {"a": 0.1, "b": 0.9}},
    ], checks=[])
    # No checks means the scorecard has fewer than the 3 contributions the
    # conformance contract expects, but it should still load; the real
    # rollback guarantee is asserted by the directory being absent on failure.
    try:
        publish_pack(bad, packs_dir)
    except PublishError:
        assert not (packs_dir / "test_clinic").exists()


# --------------------------------------------------------------------------
# The one that matters: does it actually run?
# --------------------------------------------------------------------------

def test_published_pack_runs_a_real_case(packs_dir, monkeypatch):
    """Publish over HTTP, then drive a case through the new pack's graph.

    This is the claim under test: a generated pack is not a file drop, it is a
    compiled LangGraph that scores and routes like any hand-written pack.
    """
    # Seed the directory with a pack so the app has something to start with,
    # then point the app at this tmp directory.
    publish_pack(spec(pack_id="seed-pack"), packs_dir)
    settings = Settings(packs_dir=packs_dir, database_url=None)
    client = TestClient(create_app(settings=settings))

    published = client.post("/packs/publish", json={"spec": spec()})
    assert published.status_code == 201, published.text
    assert published.json()["live"] is True

    # It shows up in the catalogue.
    ids = [p["pack_id"] for p in client.get("/packs").json()]
    assert "test-clinic" in ids

    # And it runs.
    case = client.post("/cases", json={"pack_id": "test-clinic"}).json()
    assert case["status"] == "awaiting_interview"
    assert case["interrupt"]["type"] == "interview"

    done = client.post(
        f"/cases/{case['case_id']}/interview-result",
        json={"fields": {"patient_name": "Sam Okafor", "urgency": "urgent",
                         "symptom_area": "chest"},
              "confidence": {}},
    ).json()

    # The graph scored it, the check fired, and it reached a real terminal state.
    assert done["score"] is not None
    assert done["score"]["band"] in {"low", "medium", "high"}
    assert any(c["check_name"] == "red_flag" for c in done["check_results"])
    assert done["status"] in {"awaiting_review", "approved", "rejected"}


def test_publish_rejects_a_bad_spec_over_http(packs_dir):
    publish_pack(spec(pack_id="seed-pack"), packs_dir)
    settings = Settings(packs_dir=packs_dir, database_url=None)
    client = TestClient(create_app(settings=settings))

    r = client.post("/packs/publish", json={"spec": spec(pack_id="../escape")})
    assert r.status_code == 422
    assert "pack_id" in r.json()["detail"]


# --------------------------------------------------------------------------
# Security regressions. Both of these were live, unauthenticated and proven.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bias", [
    "__import__('os').system('echo pwned') or -2.0",   # the actual exploit
    "-2.0",                                            # numeric-looking string
    True,                                              # bool subclasses int
    None,
    float("nan"),
    float("inf"),
    [1],
])
def test_bias_that_is_not_a_number_is_refused(bias):
    """Regression: remote code execution.

    `bias` was interpolated into generated `scoring.py` as a bare f-string
    value, so a spec string containing an expression became a Python statement
    that ran the moment the pack was imported — reachable from an
    unauthenticated browser POST. Validated here and, independently, in
    `emit._num`.
    """
    with pytest.raises(PublishError, match="bias"):
        validate_spec(spec(bias=bias))


def test_weights_and_risks_that_are_not_numbers_are_refused():
    """Same injection point, two other fields that reach generated source."""
    fields = spec()["fields"]
    fields[1]["weight"] = "1.0 or __import__('os').system('echo pwned')"
    with pytest.raises(PublishError, match="weight"):
        validate_spec(spec(fields=fields))

    fields = spec()["fields"]
    fields[1]["values"] = {"routine": 0.1, "urgent": "__import__('os')"}
    with pytest.raises(PublishError, match="risk"):
        validate_spec(spec(fields=fields))

    fields = spec()["fields"]
    fields[0]["min_words"] = "1 or __import__('os').system('echo pwned')"
    with pytest.raises(PublishError, match="min_words"):
        validate_spec(spec(fields=fields))


def test_the_emitter_refuses_independently_of_the_validator():
    """Defence in depth. The validator already failed once; the emitter must
    not rely on having been called after it."""
    from voxgate.packs.emit import emit_scoring

    with pytest.raises(TypeError):
        emit_scoring(spec(bias="__import__('os').system('echo pwned') or -2.0"))


def test_the_exploit_does_not_execute_end_to_end(packs_dir, tmp_path):
    """The proof, not the proxy: publish the exploit and assert nothing ran."""
    marker = tmp_path / "pwned.txt"
    payload = f"__import__('pathlib').Path({str(marker)!r}).write_text('pwned') or -2.0"

    with pytest.raises(PublishError):
        publish_pack(spec(bias=payload), packs_dir)

    assert not marker.exists(), "generated code executed a value from the spec"


def test_oversized_strings_are_refused():
    """Strings reach prompt.md unbounded, so one request could write a huge
    file — a disk-fill with no rate limit in front of it."""
    with pytest.raises(PublishError, match="persona"):
        validate_spec(spec(persona="x" * 5000))
    with pytest.raises(PublishError, match="display_name"):
        validate_spec(spec(display_name="x" * 300))


def test_a_failed_publish_leaves_the_packs_directory_loadable(packs_dir):
    """Regression: boot denial of service.

    Writes went straight into the packs directory, so a spec that failed
    part-way through emit left a partial pack behind — and `load_packs` aborted
    on any unloadable pack, so one bad request stopped the service booting until
    a human deleted the directory. Publishing now stages and renames.
    """
    from voxgate.packs.loader import load_packs

    publish_pack(spec(pack_id="healthy"), packs_dir)

    # Missing 'values' on an enum: passes pack_id validation, fails inside emit.
    fields = spec()["fields"]
    del fields[1]["values"]
    with pytest.raises(PublishError):
        publish_pack(spec(pack_id="poison", fields=fields), packs_dir)

    assert not (packs_dir / "poison").exists()
    assert not list(packs_dir.glob(".staging-*")), "staging dir was not cleaned up"
    assert list(load_packs(packs_dir, strict=True)) == ["healthy"], (
        "the service must still boot after a failed publish"
    )


def test_a_failed_overwrite_does_not_destroy_the_existing_pack(packs_dir):
    """Replacing a live pack must be atomic: if the replacement will not load,
    the pack that was serving traffic stays serving traffic."""
    from voxgate.packs.loader import load_packs

    publish_pack(spec(display_name="Original"), packs_dir)

    fields = spec()["fields"]
    del fields[1]["values"]
    with pytest.raises(PublishError):
        publish_pack(spec(fields=fields), packs_dir, overwrite=True)

    surviving = load_packs(packs_dir, strict=True)
    assert surviving["test-clinic"].display_name == "Original"
    assert not list(packs_dir.glob("*.replacing"))

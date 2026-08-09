"""Every value a spec can carry, tested for escape into code or config.

The first RCE fix in this codebase closed the four NUMERIC fields and shipped
with a test asserting "the exploit does not execute end to end" — using a
numeric payload. It passed, and the suite reported the injection closed while
`question`, a plain string, was still a working remote code execution: it was
escaped by a hand-rolled `.replace('"', '\\"')` that handles quotes but not
backslashes, so a backslash followed by a quote emitted a real string
terminator and dropped the rest of the value into code position.

That one was worse than the numeric hole it sat beside. The generated module
imported cleanly, so `publish_pack` SUCCEEDED, the pack was renamed into the
live packs directory, and the payload re-executed on every boot.

So this file is written the other way round: enumerate every field, and assert
the property for all of them. A new spec field with no entry here should be
conspicuous.
"""

import json
from pathlib import Path

import pytest
import yaml

from voxgate.packs.emit import emit_checks, emit_schema, emit_scoring, emit_yaml, write_pack
from voxgate.packs.publish import publish_pack

# A backslash then a quote: the exact shape the old escaper mishandled.
BREAKOUT = '\\" and __import__("os") or 0,\n    #'

# Every string a caller controls, and the ones an attacker would reach for.
NASTY = [
    BREAKOUT,
    '"; import os; os.system("id"); "',
    "\\",
    "\\\\",
    '\n"pack_id": "hijacked"',
    "line one\nline two",
    "\r\n\t\x00 control chars",
    "unicode ☃ and emoji 🙂",
    "'single' and \"double\"",
    "{}{{}}%s%d",
]


def spec(**overrides):
    base = {
        "pack_id": "inject-test",
        "display_name": "Injection Test",
        "gate_role": "Reviewer",
        "persona": "You are a calm interviewer.",
        "gate_reason": "anything unusual",
        "thresholds": {"low": 0.30, "high": 0.65},
        "bias": -2.5,
        "fields": [
            {"name": "free_text", "type": "text",
             "question": "What happened?", "min_words": 1},
            {"name": "urgency", "type": "enum", "weight": 1.4,
             "question": "How urgent?",
             "values": {"routine": 0.1, "urgent": 0.9}},
        ],
        "checks": [
            {"name": "red_flag", "field": "urgency",
             "flags": {"hit": ["urgent"], "review": []}},
        ],
    }
    base.update(overrides)
    return base


def with_question(question):
    fields = spec()["fields"]
    fields[0]["question"] = question
    return spec(fields=fields)


# --------------------------------------------------------------------------
# Generated Python must stay parseable and must not execute spec content
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload", NASTY)
def test_a_hostile_question_cannot_escape_the_generated_string(payload):
    """The regression. `question` reaches `REASK_HINTS` in generated Python."""
    source = emit_schema(with_question(payload))

    compile(source, "schema.py", "exec")           # must parse at all

    namespace: dict = {}
    exec(compile(source, "schema.py", "exec"), namespace)   # noqa: S102 - that is the test
    assert namespace["REASK_HINTS"]["free_text"] == payload, (
        "the question must survive as inert data, byte for byte"
    )


@pytest.mark.parametrize("payload", NASTY)
def test_hostile_check_flag_phrases_cannot_escape(payload):
    """Flag phrases are attacker-supplied strings that reach `checks.py`."""
    checks = [{"name": "red_flag", "field": "urgency",
               "flags": {"hit": [payload], "review": []}}]
    source = emit_checks(spec(checks=checks))

    namespace: dict = {}
    exec(compile(source, "checks.py", "exec"), namespace)   # noqa: S102
    assert namespace["_RED_FLAG_FLAGS"]["hit"] == [payload]


def test_every_emitted_module_parses_with_hostile_input_everywhere_at_once():
    """Not one field at a time — all of them, together."""
    fields = [
        {"name": "free_text", "type": "text", "question": BREAKOUT, "min_words": 1},
        {"name": "urgency", "type": "enum", "weight": 1.4, "question": BREAKOUT,
         "values": {"routine": 0.1, "urgent": 0.9}},
    ]
    hostile = spec(
        fields=fields,
        checks=[{"name": "red_flag", "field": "urgency",
                 "flags": {"hit": [BREAKOUT], "review": [BREAKOUT]}}],
    )
    for name, source in (("schema.py", emit_schema(hostile)),
                         ("checks.py", emit_checks(hostile)),
                         ("scoring.py", emit_scoring(hostile))):
        compile(source, name, "exec")


def test_the_emitter_refuses_a_non_string_where_a_string_belongs():
    """Defence in depth, mirroring `_num`. This module must be safe when called
    without the validator, because the validator has already been wrong once."""
    with pytest.raises(TypeError):
        emit_schema(with_question({"not": "a string"}))


# --------------------------------------------------------------------------
# pack.yaml: not code, but the loader trusts it completely
# --------------------------------------------------------------------------

def test_a_newline_in_display_name_cannot_hijack_the_pack_id():
    """Confirmed before the fix: `display_name` of `Evil\\npack_id: hijacked`
    emitted a second `pack_id` key, and the later one won — so the pack loaded
    under an identity that did not match the directory it was written to, while
    `pack_id` is what the registry, the API and the graph cache are keyed on."""
    parsed = yaml.safe_load(emit_yaml(spec(display_name="Evil\npack_id: hijacked")))
    assert parsed["pack_id"] == "inject-test"
    assert parsed["display_name"] == "Evil\npack_id: hijacked"


@pytest.mark.parametrize("payload", NASTY)
def test_pack_yaml_survives_hostile_names(payload):
    parsed = yaml.safe_load(emit_yaml(spec(display_name=payload, gate_role=payload)))
    assert parsed["pack_id"] == "inject-test"
    assert parsed["display_name"] == payload
    assert parsed["gate_role"] == payload


# --------------------------------------------------------------------------
# The whole path, not a component of it
# --------------------------------------------------------------------------

def test_publishing_a_hostile_question_writes_no_file_and_runs_no_code(tmp_path):
    """The end-to-end proof the first version of this test should have been.

    `publish_pack` writes generated Python and imports it. If the payload
    escapes, this marker exists.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    marker = tmp_path / "pwned.txt"
    payload = (
        '\\" and __import__(%s).Path(%s).write_text(%s) or 0,\n    #'
        % (json.dumps("pathlib"), json.dumps(str(marker)), json.dumps("pwned"))
    )

    pack = publish_pack(with_question(payload), packs_dir)

    assert not marker.exists(), "generated code executed a value from the spec"
    assert pack.reask_hints["free_text"] == payload, "and it is still just data"


def test_a_published_hostile_pack_does_not_execute_on_a_later_boot(tmp_path):
    """The part that made this worse than the numeric hole.

    The malicious module imported cleanly, so publish succeeded and the pack was
    renamed into the live packs directory — where `load_packs` re-executed it on
    every start. Skipping unloadable packs does not help: this one loads.
    """
    from voxgate.packs.loader import load_packs

    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    marker = tmp_path / "pwned-on-boot.txt"
    payload = (
        '\\" and __import__(%s).Path(%s).write_text(%s) or 0,\n    #'
        % (json.dumps("pathlib"), json.dumps(str(marker)), json.dumps("boot"))
    )
    write_pack(with_question(payload), packs_dir)

    load_packs(packs_dir)          # the boot path

    assert not marker.exists(), "a published pack executed spec content at boot"


def test_write_pack_cannot_be_talked_into_leaving_the_packs_directory(tmp_path):
    """`pack_id` becomes a directory name. publish validates it; this asserts
    the emitter is not the only thing standing between a spec and the disk."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    with pytest.raises(Exception):
        publish_pack(spec(pack_id="../../escape"), packs_dir)
    assert not (tmp_path.parent / "escape").exists()
    assert list(Path(packs_dir).iterdir()) == []

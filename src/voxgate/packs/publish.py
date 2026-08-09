"""Turn a drafted spec into a live pack: files on disk, then a compiled graph.

This is what closes the loop. A pack published here is byte-identical to one
produced by `scripts/generate_packs.py`, because both call the same emitters —
which is the only way "every agent is a folder of Python" stays literally true
rather than becoming marketing.

Safety, stated plainly. This writes generated Python to the server's filesystem
and imports it.

An earlier version of this docstring claimed "there is no path from spec
content to executable statements". That was FALSE. `bias`, `weight` and
`min_words` were interpolated into generated source as bare f-string values
with no type check, so a spec containing
`"bias": "__import__('os').system('...') or -2.0"` executed on import. It was
reachable unauthenticated from the browser. Both layers are now closed:

  1. Every numeric is type-checked here AND rendered through `emit._num()`,
     which raises on anything that is not a finite number. Two independent
     layers, because one of them already failed once.
  2. Every string written into generated source is escaped by `json.dumps`,
     and every name must be a validated identifier.
  3. `pack_id` is validated against a strict pattern before it touches a path,
     so no traversal and no absolute paths.
  4. Writes go to a temporary directory and are renamed into place only after
     the pack loads. A partial write can no longer poison the packs directory.

None of that makes this endpoint safe to expose publicly. It must sit behind
authentication before anyone but the operator can reach it, and it refuses to
overwrite an existing pack unless explicitly told to.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PACK_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

# Mirrors voxgate.ml.authoring.RESERVED. Duplicated deliberately: publishing
# must be safe even when called with a hand-written spec that never passed
# through the drafting validator.
RESERVED = {"case_id", "pack_id", "status", "score", "decision", "audit"}


class PublishError(Exception):
    """The spec cannot be published as written."""


def _number(value, label: str, low: float, high: float) -> None:
    """Reject anything that is not a finite in-range number.

    bool is excluded explicitly: it subclasses int, so `True` would otherwise
    pass as a weight and emit `Feature(..., True, ...)`.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublishError(f"{label} must be a number, got {type(value).__name__}")
    if value != value or value in (float("inf"), float("-inf")):
        raise PublishError(f"{label} must be finite")
    if not low <= value <= high:
        raise PublishError(f"{label} must be between {low} and {high}, got {value}")


def validate_spec(spec: dict[str, Any]) -> None:
    """Reject anything that could produce broken or unsafe generated code.

    Raises on the first problem rather than collecting: a spec that fails here
    has already been through the drafting validator, so a failure means
    something structural, not something a reviewer should triage.
    """
    pack_id = spec.get("pack_id", "")
    if not PACK_ID.match(pack_id):
        raise PublishError(
            f"pack_id {pack_id!r} must be lowercase words joined by hyphens"
        )

    for key in ("display_name", "gate_role", "persona"):
        if not str(spec.get(key, "")).strip():
            raise PublishError(f"{key} is required")

    fields = spec.get("fields") or []
    if not 2 <= len(fields) <= 12:
        raise PublishError(f"a pack needs 2 to 12 fields, got {len(fields)}")

    names: set[str] = set()
    for f in fields:
        name = f.get("name", "")
        if not IDENTIFIER.match(name):
            raise PublishError(f"field name {name!r} is not a valid identifier")
        if name in RESERVED:
            raise PublishError(f"field name {name!r} is reserved by the platform")
        if name in names:
            raise PublishError(f"duplicate field name {name!r}")
        names.add(name)

        if f.get("type") == "enum":
            values = f.get("values") or {}
            if len(values) < 2:
                raise PublishError(f"enum field {name!r} needs at least two values")
            for value in values:
                if not IDENTIFIER.match(str(value)):
                    raise PublishError(
                        f"enum value {value!r} on {name!r} is not a valid identifier"
                    )
        elif f.get("type") != "text":
            raise PublishError(f"field {name!r} has unsupported type {f.get('type')!r}")

    for c in spec.get("checks") or []:
        cname = c.get("name", "")
        if not IDENTIFIER.match(cname):
            raise PublishError(f"check name {cname!r} is not a valid identifier")
        if c.get("field") not in names:
            raise PublishError(
                f"check {cname!r} reads {c.get('field')!r}, which is not a field"
            )

    # Numerics reach generated source. A string here was arbitrary code.
    _number(spec.get("bias", -2.5), "bias", -10.0, 10.0)

    for f in fields:
        if f.get("type") == "enum":
            _number(f.get("weight", 1.0), f"{f['name']}.weight", 0.0, 10.0)
            for value, risk in (f.get("values") or {}).items():
                _number(risk, f"{f['name']}.{value} risk", 0.0, 1.0)
        else:
            _number(f.get("min_words", 1), f"{f['name']}.min_words", 0, 50)

    # Strings reach prompt.md and generated docstrings. Unbounded means one
    # request can write an arbitrarily large file.
    for key, limit in (("display_name", 200), ("gate_role", 120),
                       ("persona", 4000), ("gate_reason", 500)):
        if len(str(spec.get(key, ""))) > limit:
            raise PublishError(f"{key} exceeds {limit} characters")
    for f in fields:
        if len(str(f.get("question", ""))) > 500:
            raise PublishError(f"question on {f['name']!r} exceeds 500 characters")
    checks = spec.get("checks") or []
    if len(checks) > 12:
        raise PublishError(f"a pack supports at most 12 checks, got {len(checks)}")
    for c in checks:
        for band in ("hit", "review"):
            phrases = (c.get("flags") or {}).get(band, [])
            if len(phrases) > 50:
                raise PublishError(f"check {c.get('name')!r} has too many {band} phrases")
            for phrase in phrases:
                if len(str(phrase)) > 200:
                    raise PublishError(f"phrase in {c.get('name')!r} exceeds 200 characters")

    thresholds = spec.get("thresholds") or {}
    low, high = thresholds.get("low"), thresholds.get("high")
    if not (isinstance(low, (int, float)) and isinstance(high, (int, float))):
        raise PublishError("thresholds.low and thresholds.high are required")
    if not 0 < low < high < 1:
        raise PublishError(f"thresholds must satisfy 0 < {low} < {high} < 1")


def publish_pack(
    spec: dict[str, Any],
    packs_dir: Path,
    *,
    overwrite: bool = False,
):
    """Write the pack, load it, and return the loaded Pack.

    Loading is the real test: if the emitted code does not import, or the pack
    does not satisfy the loader contract, this raises and the caller can delete
    the directory rather than leaving a broken pack that breaks every later
    `load_packs` call.
    """
    import shutil
    import tempfile

    from voxgate.packs.emit import write_pack
    from voxgate.packs.loader import load_pack

    validate_spec(spec)

    directory = packs_dir / spec["pack_id"].replace("-", "_")
    if directory.exists() and not overwrite:
        raise PublishError(
            f"pack {spec['pack_id']!r} already exists; publish with overwrite to replace it"
        )

    # Belt and braces over the pack_id pattern: a path escaping the packs
    # directory must never be written, even if the pattern is later loosened.
    if not str(directory.resolve()).startswith(str(packs_dir.resolve())):
        raise PublishError("refusing to write outside the packs directory")

    # Stage in a sibling temp directory, then rename. Writing directly meant a
    # spec that failed mid-emit left a partial pack on disk, and load_packs
    # aborts on any unloadable pack, so one bad request permanently broke boot.
    # Sibling, not the system temp dir, so the rename is same-filesystem.
    packs_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=packs_dir))
    try:
        write_pack(spec, staging)
        built = staging / spec["pack_id"].replace("-", "_")
        # Loading is the real test: emitted code that does not import must never
        # reach the packs directory.
        load_pack(built)

        backup = None
        if directory.exists():
            # Keep the previous pack until the replacement is in place, so a
            # failed overwrite does not destroy a working pack.
            backup = directory.with_name(directory.name + ".replacing")
            shutil.rmtree(backup, ignore_errors=True)
            directory.rename(backup)
        try:
            built.rename(directory)
        except Exception:
            if backup is not None:
                backup.rename(directory)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)

        return load_pack(directory)
    except PublishError:
        raise
    except Exception as exc:
        # Every failure mode, not just PublishError. A KeyError from a missing
        # spec value previously escaped as an unhandled 500.
        raise PublishError(f"could not publish pack: {type(exc).__name__}: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def register(runner, pack, checkpointer) -> None:
    """Make a freshly published pack live without restarting the process.

    The runner builds one compiled graph per pack at construction, so a new pack
    needs both the pack record and its own compiled graph. Without this the pack
    exists on disk but `POST /cases` against it raises KeyError.
    """
    from voxgate.graph.build import build_graph

    # Through the runner, which rebinds new dicts rather than mutating ones a
    # concurrent `GET /packs` may be iterating.
    runner.add_pack(pack, build_graph(pack, checkpointer))

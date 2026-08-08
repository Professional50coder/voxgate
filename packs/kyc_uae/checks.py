import json
from pathlib import Path
from rapidfuzz import fuzz
from voxgate.ml.name_match import NameMatcher
from voxgate.packs.base import CheckResult

DATA = Path(__file__).parent / "data"
_sanctions = json.loads((DATA / "sanctions.json").read_text(encoding="utf-8"))["entries"]
_peps = json.loads((DATA / "peps.json").read_text(encoding="utf-8"))["entries"]
_media = json.loads((DATA / "adverse_media.json").read_text(encoding="utf-8"))["entries"]
COUNTRIES = json.loads((DATA / "countries.json").read_text(encoding="utf-8"))["countries"]

_STATUS = {"strong": "hit", "review": "review", "clear": "clear"}

def _screen(name, entries, check_name, fields):
    matcher = NameMatcher(entries)   # embedder wired in Plan 2+ via config; None is valid
    cands = matcher.match(name, dob=fields.get("dob"), nationality=fields.get("nationality"))
    top = cands[0] if cands else None
    return CheckResult(
        check_name=check_name,
        status=_STATUS[top.band] if top else "clear",
        score=top.combined if top else 0.0,
        details={"candidates": [c.model_dump() for c in cands]})

def sanctions_screen(fields: dict) -> CheckResult:
    return _screen(fields["full_name"], _sanctions, "sanctions", fields)
sanctions_screen.check_name = "sanctions"

def pep_screen(fields: dict) -> CheckResult:
    return _screen(fields["full_name"], _peps, "pep", fields)
pep_screen.check_name = "pep"

def adverse_media(fields: dict) -> CheckResult:
    hits = [m for m in _media
            if fuzz.token_set_ratio(fields["full_name"].lower(), m["name"].lower()) > 85]
    worst = max((m["severity"] for m in hits), default=0.0)
    return CheckResult(check_name="adverse_media",
                       status="review" if worst >= 0.5 else "clear",
                       score=worst, details={"articles": hits})
adverse_media.check_name = "adverse_media"

CHECKS = [sanctions_screen, pep_screen, adverse_media]

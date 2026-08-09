### Task 2: Transliteration variants + name-matching ensemble

**Files:**
- Create: `src/voxgate/ml/variants.py`, `src/voxgate/ml/name_match.py`, `tests/test_name_match.py`

**Interfaces:**
- Produces:
  - `variants.expand_variants(name: str) -> list[str]` — normalized romanization variants incl. the input.
  - `name_match.MatchCandidate` (pydantic): `entry_id: str`, `entry_name: str`, `list_name: str`, `jaro_winkler: float`, `token_set: float`, `embedding_sim: float | None`, `combined: float`, `band: str` (`"clear" | "review" | "strong"`).
  - `name_match.NameMatcher(entries: list[dict], embedder: Callable[[str], "np.ndarray"] | None = None)`; entries carry `id, name, list, dob, nationality, aliases`. Method: `match(name: str, dob: str | None = None, nationality: str | None = None, top_k: int = 5) -> list[MatchCandidate]` sorted by `combined` desc.
  - Bands: `combined >= 0.85` → `strong`; `>= 0.65` → `review`; else `clear`. Ensemble weights `0.35*jw + 0.25*token_set + 0.40*emb`; with `embedder=None` renormalize to `0.58*jw + 0.42*token_set`. DOB exact match boosts `combined` by `+0.07`, nationality match `+0.03` (cap 1.0).

- [ ] **Step 1: Write the failing tests** — `tests/test_name_match.py`

```python
from voxgate.ml.variants import expand_variants
from voxgate.ml.name_match import NameMatcher

ENTRIES = [
    {"id": "UN-001", "name": "Mohammed Al Rashid", "list": "UN Consolidated",
     "dob": "1975-03-02", "nationality": "SY", "aliases": ["Abu Khalid"]},
    {"id": "OFAC-77", "name": "Dmitri Volkov", "list": "OFAC SDN",
     "dob": "1969-11-20", "nationality": "RU", "aliases": []},
]

def test_variants_cover_common_romanizations():
    v = expand_variants("Muhammad Al-Rashid")
    joined = " | ".join(v)
    assert "mohammed al rashid" in joined

def test_transliteration_variant_matches_strongly():
    m = NameMatcher(ENTRIES)
    top = m.match("Muhammad Al-Rashid", dob="1975-03-02", nationality="SY")[0]
    assert top.entry_id == "UN-001"
    assert top.band == "strong"
    assert top.combined > 0.9

def test_different_name_is_clear():
    m = NameMatcher(ENTRIES)
    res = m.match("Priya Raghavan", dob="1990-01-01", nationality="IN")
    assert all(c.band == "clear" for c in res)

def test_alias_is_searched():
    m = NameMatcher(ENTRIES)
    top = m.match("Abu Khalid")[0]
    assert top.entry_id == "UN-001"
    assert top.band != "clear"

def test_embedder_changes_score_and_renormalization_works():
    import numpy as np
    def fake_embedder(text: str):
        vec = np.zeros(4); vec[hash(text) % 4] = 1.0; return vec
    with_emb = NameMatcher(ENTRIES, embedder=fake_embedder).match("Dmitri Volkov")[0]
    without = NameMatcher(ENTRIES).match("Dmitri Volkov")[0]
    assert with_emb.embedding_sim is not None
    assert without.embedding_sim is None
    assert without.band == "strong"   # exact name must still hit without embeddings
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_name_match.py -v`
Expected: FAIL — `ModuleNotFoundError: voxgate.ml.variants`

- [ ] **Step 3: Implement `src/voxgate/ml/variants.py`**

```python
import re

# canonical token -> known romanization variants (curated, extend freely)
_VARIANTS: dict[str, list[str]] = {
    "mohammed": ["muhammad", "mohamed", "mohammad", "mohd", "muhammed"],
    "abdul": ["abdel", "abd al", "abdal", "abdol"],
    "hussein": ["husain", "hussain", "husayn"],
    "rashid": ["rasheed", "rachid"],
    "said": ["saeed", "sayid", "sayyid"],
    "aisha": ["ayesha", "aysha"],
    "khalid": ["khaled", "haled"],
    "jamal": ["gamal", "djamel"],
}
_CANON = {v: k for k, vs in _VARIANTS.items() for v in vs}

def _norm(name: str) -> str:
    name = name.lower().replace("-", " ").replace("'", "")
    name = re.sub(r"\bal[\s-]?", "al ", name)
    return re.sub(r"\s+", " ", name).strip()

def expand_variants(name: str) -> list[str]:
    base = _norm(name)
    tokens = base.split()
    canon_tokens = [_CANON.get(t, t) for t in tokens]
    out = {base, " ".join(canon_tokens)}
    for i, tok in enumerate(canon_tokens):          # one substitution at a time
        for var in _VARIANTS.get(tok, []):
            out.add(" ".join(canon_tokens[:i] + [var] + canon_tokens[i + 1:]))
    return sorted(out)
```

- [ ] **Step 4: Implement `src/voxgate/ml/name_match.py`**

```python
from typing import Callable
import numpy as np
from pydantic import BaseModel
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from .variants import expand_variants, _norm

class MatchCandidate(BaseModel):
    entry_id: str
    entry_name: str
    list_name: str
    jaro_winkler: float
    token_set: float
    embedding_sim: float | None
    combined: float
    band: str

def _band(score: float) -> str:
    return "strong" if score >= 0.85 else "review" if score >= 0.65 else "clear"

class NameMatcher:
    def __init__(self, entries: list[dict], embedder: Callable | None = None):
        self.entries = entries
        self.embedder = embedder

    def _emb_sim(self, a: str, b: str) -> float | None:
        if self.embedder is None:
            return None
        va, vb = self.embedder(a), self.embedder(b)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
        return float(np.dot(va, vb) / denom)

    def match(self, name, dob=None, nationality=None, top_k=5) -> list[MatchCandidate]:
        queries = expand_variants(name)
        out = []
        for e in self.entries:
            targets = [e["name"], *e.get("aliases", [])]
            best = (0.0, 0.0, None)  # jw, ts, emb
            for q in queries:
                for t in targets:
                    tn = _norm(t)
                    jw = JaroWinkler.normalized_similarity(q, tn)
                    ts = fuzz.token_set_ratio(q, tn) / 100.0
                    emb = self._emb_sim(q, tn)
                    score = 0.35 * jw + 0.25 * ts + 0.40 * (emb or 0.0)
                    if score > 0.35 * best[0] + 0.25 * best[1] + 0.40 * (best[2] or 0.0):
                        best = (jw, ts, emb)
            jw, ts, emb = best
            combined = (0.35 * jw + 0.25 * ts + 0.40 * emb) if emb is not None \
                       else (0.58 * jw + 0.42 * ts)
            if dob and e.get("dob") == dob:
                combined = min(1.0, combined + 0.07)
            if nationality and e.get("nationality") == nationality:
                combined = min(1.0, combined + 0.03)
            out.append(MatchCandidate(
                entry_id=e["id"], entry_name=e["name"], list_name=e["list"],
                jaro_winkler=round(jw, 4), token_set=round(ts, 4),
                embedding_sim=None if emb is None else round(emb, 4),
                combined=round(combined, 4), band=_band(combined)))
        return sorted(out, key=lambda c: c.combined, reverse=True)[:top_k]
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_name_match.py -v`
Expected: 5 PASS. If `test_transliteration_variant_matches_strongly` fails on the 0.9 bound, the bug is in `_norm`'s `al-` handling — do not lower the assertion.

---


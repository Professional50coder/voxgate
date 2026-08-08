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

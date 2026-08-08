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

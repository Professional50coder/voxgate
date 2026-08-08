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

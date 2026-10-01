from pathlib import Path
from voxgate.config import Settings, get_settings

def test_defaults(monkeypatch):
    monkeypatch.delenv("VOXGATE_DATABASE_URL", raising=False)
    s = Settings()
    assert s.database_url is None
    assert s.packs_dir.name == "packs"

def test_env_override(monkeypatch):
    monkeypatch.setenv("VOXGATE_DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("VOXGATE_PACKS_DIR", str(Path("C:/tmp/pk")))
    s = Settings()
    assert s.database_url == "postgresql://x"
    assert s.packs_dir == Path("C:/tmp/pk")


def test_secrets_are_stripped_of_byte_order_marks_and_whitespace():
    from voxgate.config import Settings
    s = Settings(cartesia_api_key="﻿sk_abc \n", groq_api_key="﻿", api_keys=" k1,k2 ")
    assert s.cartesia_api_key == "sk_abc"
    assert s.groq_api_key is None
    assert s.api_keys == "k1,k2"
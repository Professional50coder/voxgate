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

def test_cartesia_alias(monkeypatch):
    monkeypatch.setenv("CARTESIA_API_KEY", "sk_car_test")
    s = Settings()
    assert s.cartesia_api_key == "sk_car_test"

def test_cartesia_reads_real_env():
    s = Settings()
    if s.cartesia_api_key:
        assert s.cartesia_api_key.startswith("sk_car_")

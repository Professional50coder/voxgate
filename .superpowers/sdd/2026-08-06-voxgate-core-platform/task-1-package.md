# Task 1 review package — files as implemented

=== FILE: pyproject.toml ===
[project]
name = "voxgate"
version = "0.1.0"
description = "Voice-driven durable workflow orchestrator (LangGraph + Pipecat)"
requires-python = ">=3.12"
dependencies = [
    "langgraph>=0.4",
    "langgraph-checkpoint-postgres>=2.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "pyyaml>=6.0",
    "rapidfuzz>=3.9",
    "numpy>=1.26",
    "psycopg[binary]>=3.1",
]

[project.optional-dependencies]
embeddings = ["sentence-transformers>=3.0"]

[dependency-groups]
dev = ["pytest>=8.2", "httpx>=0.27", "websockets>=12.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/voxgate"]

[tool.pytest.ini_options]
testpaths = ["tests"]

=== FILE: docker-compose.yml ===
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: voxgate
      POSTGRES_PASSWORD: voxgate
      POSTGRES_DB: voxgate
    ports: ["5433:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
volumes:
  pgdata:

=== FILE: .env.example ===
# Leave DATABASE_URL unset for in-memory dev mode (no persistence)
VOXGATE_DATABASE_URL=postgresql://voxgate:voxgate@localhost:5433/voxgate

=== FILE: src/voxgate/config.py ===
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOXGATE_", env_file=".env", extra="ignore")
    database_url: str | None = None
    packs_dir: Path = REPO_ROOT / "packs"

def get_settings() -> Settings:
    return Settings()

=== FILE: tests/test_config.py ===
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

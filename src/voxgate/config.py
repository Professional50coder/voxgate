from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOXGATE_", env_file=".env", extra="ignore")
    database_url: str | None = None
    packs_dir: Path = REPO_ROOT / "packs"
    traces_dir: Path = REPO_ROOT / "traces"
    # Context.dev enrichment key. Read from CONTEXT_DEV_API_KEY (its own env-var
    # convention, not the VOXGATE_ prefix) via an explicit alias; optional.
    context_dev_api_key: str | None = Field(default=None, validation_alias="CONTEXT_DEV_API_KEY")
    # Groq (free-tier) LLM brain key. Read from GROQ_API_KEY via explicit alias.
    # Used to interpret raw spoken answers into canonical field values (and,
    # later, as the Pipecat LLM stage). Optional: absent -> raw transcript fallback.
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    # Cartesia (natural Sonic voice) TTS key, used by the Pipecat voice agent.
    # Read from CARTESIA_API_KEY via explicit alias. Optional: absent -> no TTS.
    cartesia_api_key: str | None = Field(default=None, validation_alias="CARTESIA_API_KEY")

def get_settings() -> Settings:
    return Settings()

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOXGATE_", env_file=REPO_ROOT / ".env", extra="ignore",
        populate_by_name=True)
    database_url: str | None = None
    packs_dir: Path = REPO_ROOT / "packs"

    # Comma-separated operator keys. Unset means authentication is OFF and the
    # operator endpoints are open; that is reported by /health/ready and warned
    # at startup rather than being silently insecure. See service/auth.py for
    # which routes this covers and why the applicant flow is not one of them.
    api_keys: str | None = Field(default=None, alias="VOXGATE_API_KEYS")

    # Requests per operator key per day on the endpoints that spend an LLM call
    # or write generated Python. A ceiling against runaway loops, not a pricing
    # tier -- an operator exploring the authoring flow should never meet it.
    quota_daily_limit: int = Field(default=500, alias="VOXGATE_QUOTA_DAILY_LIMIT")

    # Groq. Note these carry no VOXGATE_ prefix: the `groq` SDK and every other
    # tool expect the bare GROQ_API_KEY name, so aliasing keeps one variable in
    # .env rather than two that can drift apart.
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-20b", alias="GROQ_MODEL")

    # Exa. Same reasoning as Groq: the exa_py SDK expects the bare name.
    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")

    # Optional comma-separated pool. Groq rate limits are per key AND per model,
    # so N keys times M models is the real headroom.
    groq_api_keys: str | None = Field(default=None, alias="GROQ_API_KEYS")

    def groq_key_pool(self) -> list[str]:
        """Every usable key, preferred first, de-duplicated."""
        pool: list[str] = []
        if self.groq_api_key:
            pool.append(self.groq_api_key.strip())
        for raw in (self.groq_api_keys or "").split(","):
            key = raw.strip()
            if key and key not in pool:
                pool.append(key)
        return pool

    # Browser origins allowed to call this API. The Next.js app in apps/web runs
    # on a different origin than the API, so without these the browser blocks
    # every request while curl keeps working, which reads as "backend is down".
    # Localhost defaults are for development only. In a hosted deploy the
    # frontend lives on a real domain, and a request from it is cross-origin:
    # without the domain listed here the browser blocks every call while curl
    # keeps working, which presents as "the backend is down".
    #
    # Set VOXGATE_CORS_ORIGINS to a comma-separated list of real origins.
    # Scheme and port must match exactly; https://app.example.com and
    # http://app.example.com are different origins to a browser.
    cors_origins_raw: str = Field(
        default=(
            "http://localhost:3000,http://127.0.0.1:3000,"
            "http://localhost:3111,http://127.0.0.1:3111"
        ),
        alias="VOXGATE_CORS_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

def get_settings() -> Settings:
    return Settings()

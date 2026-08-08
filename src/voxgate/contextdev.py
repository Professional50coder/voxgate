"""Optional Context.dev client (brand / web-scraping enrichment).

Context.dev (https://context.dev) turns a domain/name into structured brand
data and clean markdown. It is **optional** in VoxGate: every entry point here
returns ``None`` when no API key is configured, so the whole module is a no-op
unless the operator puts a key in ``.env`` as ``CONTEXT_DEV_API_KEY``. No
imports in the platform core depend on this module; it is a leaf utility a pack
or dashboard can opt into.

Design notes (per docs.context.dev):
- Reads the key from ``Settings.context_dev_api_key`` (aliased to
  ``CONTEXT_DEV_API_KEY``), or directly from the environment as a fallback.
- Retries the two documented transient statuses (408 cold-hit timeout, 429
  rate limit) with exponential backoff.
- Returns typed shapes or ``None``; never raises for an "enrichment not found" —
  callers treat ``None`` as "no enrichment available". Only configuration
  errors (no key) and programming errors propagate.
"""
import os
import time
import urllib.parse

import httpx

from voxgate.config import Settings, get_settings

BRAND_ENDPOINT = "https://api.context.dev/brand/retrieve"
SCRAPE_ENDPOINT = "https://api.context.dev/web/scrape/markdown"

_RETRYABLE = {408, 429}


def _key(settings: Settings | None = None) -> str | None:
    if settings is None:
        settings = get_settings()
    if settings.context_dev_api_key:
        return settings.context_dev_api_key
    return os.environ.get("CONTEXT_DEV_API_KEY") or os.environ.get("CONTEXT_API_KEY")


class _Client:
    """Minimal bearer-token client; kept internal so callers get clean helpers."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _post_json(self, url: str, payload: dict) -> dict:
        last = None
        for attempt in range(3):
            try:
                r = httpx.post(url, json=payload, headers=self._headers, timeout=20.0)
            except httpx.HTTPError as e:
                # treat transport errors as retryable up to the attempt cap
                last = RuntimeError(f"context.dev request failed: {e}")
                if attempt < 2:
                    continue
                raise last from e
            if r.status_code in _RETRYABLE and attempt < 2:
                try:
                    retry_after = float(r.headers.get("Retry-After", "0"))
                except ValueError:
                    retry_after = 0.0
                time.sleep(2 ** attempt + retry_after)
                continue
            if r.status_code == 401:
                raise PermissionError("context.dev: 401 — invalid or missing API key")
            r.raise_for_status()
            return r.json()
        raise last or RuntimeError("context.dev: unreachable")


def _client_or_none(settings: Settings | None = None):
    key = _key(settings)
    return _Client(key) if key else None


def brand_lookup(domain: str, *, settings: Settings | None = None):
    """Resolve a domain to a brand record (dict), or None if unavailable.

    Disable by leaving ``CONTEXT_DEV_API_KEY`` unset.
    """
    client = _client_or_none(settings)
    if client is None:
        return None
    try:
        data = client._post_json(BRAND_ENDPOINT, {"by_domain": domain})
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code in (404, 422):
            return None  # brand not resolvable for this input
        raise
    return data.get("brand")


def scrape_markdown(url: str, *, settings: Settings | None = None):
    """Scrape a URL to clean markdown (str), or ``None`` if unavailable."""
    client = _client_or_none(settings)
    if client is None:
        return None
    data = client._post_json(SCRAPE_ENDPOINT, {"url": url})
    return data.get("markdown")


def domain_from_identity(email: str | None = None) -> str | None:
    """Best-effort domain extraction from an email address, for use before brand_lookup."""
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower()


def is_enabled(settings: Settings | None = None) -> bool:
    """Whether a Context.dev key is configured."""
    return _client_or_none(settings) is not None
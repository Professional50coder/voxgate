"""API-key authentication for the operator surfaces.

Deliberately small. This is not a user system: there are no accounts, no
sessions and no passwords. It is one shared secret that separates "anyone with
an invite link" from "someone who runs this deployment", which is the only
distinction the product currently needs — and it is the distinction that stops
`POST /packs/publish` from being a public endpoint that writes Python to the
server and imports it.

**Which routes are open, and why.** The split is not by risk of the handler, it
is by who legitimately calls it:

  open       Everything the applicant flow touches. An applicant follows an
             invite link, answers questions and submits. They have no account
             and never will, so requiring a key would mean handing the key to
             every applicant, which is the same as having no key.
  protected  Everything an operator touches: the case board, reviewer
             decisions, drafting a pack with an LLM, and publishing one.

A consequence worth stating plainly: `GET /cases/{id}` is open, so a case UUID
is a bearer capability. Anyone holding the link can read that one case. That is
the invite-link model working as intended, not an oversight — but it does mean
case ids must be treated as secrets, and they are v4 UUIDs for that reason.
`GET /cases` (the whole board) is protected, because that is the difference
between leaking one case and leaking all of them.

**When no key is configured**, authentication is off and every route is open.
That keeps development and the test suite working without ceremony. It is
reported by `/health/ready` as `auth: "disabled"` and logged as a warning at
startup, so a deployment that forgot to set one says so out loud rather than
looking healthy while being wide open.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


def parse_keys(raw: str | None) -> list[str]:
    """Split a comma-separated key list, dropping blanks."""
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


def key_matches(presented: str, allowed: list[str]) -> bool:
    """Constant-time comparison against every configured key.

    `hmac.compare_digest` rather than `==`, and every key is checked rather than
    returning on the first match, so neither the comparison nor the loop leaks
    how much of a guess was correct through timing.
    """
    found = False
    for key in allowed:
        if hmac.compare_digest(presented, key):
            found = True
    return found


def build_admin_guard(settings):
    """A FastAPI dependency that admits operators, given these settings.

    Returned as a closure rather than reading global settings, because
    `create_app` is called with explicit settings in tests and in any embedding
    of this app — a dependency that reached for `get_settings()` would ignore
    them and silently authenticate against the wrong configuration.
    """
    allowed = parse_keys(settings.api_keys)

    if not allowed:
        logger.warning(
            "VOXGATE_API_KEYS is not set: the operator endpoints "
            "(/packs/publish, /packs/draft, the case board and reviewer "
            "decisions) are UNAUTHENTICATED. Set it before exposing this "
            "service publicly."
        )

    def require_operator(
        x_api_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> None:
        if not allowed:
            return

        presented = x_api_key
        if not presented and authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() == "bearer":
                presented = token.strip()

        if not presented:
            # 401 with a challenge, not 403: the client has not authenticated
            # rather than been refused, and the header tells it how.
            raise HTTPException(
                401,
                "operator credentials required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not key_matches(presented, allowed):
            raise HTTPException(403, "invalid credentials")

    return require_operator

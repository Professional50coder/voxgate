#!/usr/bin/env python3
"""Push local .env values into GitHub Actions repository secrets safely.

Usage:
    GITHUB_TOKEN=ghp_... python scripts/push_env_secrets.py \
        [--repo Professional50coder/voxgate] [--env-file .env] [--all]

Only variables that look like credentials are uploaded unless --all is given
(match: contains KEY, SECRET, TOKEN, or PASSWORD, case-insensitive). Values
are encrypted client-side with the repo's public key (libsodium sealed box)
before upload and are never printed, logged, or written anywhere.

Requires: pynacl (uv run --with pynacl python scripts/push_env_secrets.py)
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from pathlib import Path

API = "https://api.github.com"
SECRET_PATTERN = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.IGNORECASE)


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def repo_key(owner: str, repo: str, token: str) -> tuple[str, str]:
    import httpx

    r = httpx.get(f"{API}/repos/{owner}/{repo}/actions/secrets/public-key",
                  headers=_headers(token), timeout=30.0)
    r.raise_for_status()
    data = r.json()
    return data["key_id"], data["key"]


def seal(public_key_b64: str, raw: bytes) -> str:
    from nacl import encoding, public

    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    return base64.b64encode(box.encrypt(raw)).decode()


def put_secret(owner: str, repo: str, token: str, name: str,
               key_id: str, encrypted_b64: str) -> None:
    import httpx

    r = httpx.put(
        f"{API}/repos/{owner}/{repo}/actions/secrets/{name}",
        headers=_headers(token),
        json={"encrypted_value": encrypted_b64, "key_id": key_id},
        timeout=30.0)
    r.raise_for_status()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="Professional50coder/voxgate")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--all", action="store_true",
                    help="upload every variable, not just credential-looking ones")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("error: set GITHUB_TOKEN (a fine-grained/classic PAT with "
              "repo secrets write)", file=sys.stderr)
        return 2

    values = parse_env(Path(args.env_file))
    selected = {k: v for k, v in values.items()
                if args.all or SECRET_PATTERN.search(k)}
    if not selected:
        print("nothing to upload: no credential-looking variables found")
        return 1

    owner, _, repo = args.repo.partition("/")
    key_id, pub = repo_key(owner, repo, token)
    for name, value in selected.items():
        put_secret(owner, repo, token, name, key_id, seal(pub, value.encode()))
        print(f"set {name} ({len(value)} chars) -> {owner}/{repo}")
    print("done: %d secret(s) updated" % len(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

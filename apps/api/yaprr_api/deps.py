from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from yaprr_api.settings import get_settings


def require_worker(x_worker_token: str = Header(default="")) -> None:
    """Endpoints the voice worker calls (runtime config, call ingest)."""
    if not hmac.compare_digest(x_worker_token, get_settings().worker_token):
        raise HTTPException(status_code=401, detail="invalid worker token")


def is_admin(authorization: str) -> bool:
    expected = get_settings().admin_token
    if not expected:
        return True  # local dev: no token configured
    token = authorization.removeprefix("Bearer ").strip()
    return hmac.compare_digest(token, expected)


def require_admin(authorization: str = Header(default="")) -> None:
    """Anything that changes data or costs money. Open when ADMIN_TOKEN is unset (local dev)."""
    if not is_admin(authorization):
        raise HTTPException(status_code=401, detail="missing or invalid access token")


def require_read(authorization: str = Header(default="")) -> bool:
    """GET endpoints. Admins always; visitors too when PUBLIC_READ is on.
    Returns True for admins, so handlers can hide private fields from visitors."""
    if is_admin(authorization):
        return True
    if get_settings().public_read:
        return False
    raise HTTPException(status_code=401, detail="missing or invalid access token")

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from yaprr_api.settings import get_settings


def require_worker(x_worker_token: str = Header(default="")) -> None:
    """Endpoints the voice worker calls (runtime config, call ingest)."""
    if not hmac.compare_digest(x_worker_token, get_settings().worker_token):
        raise HTTPException(status_code=401, detail="invalid worker token")

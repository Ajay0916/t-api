import hmac
import os

from fastapi import Request, Security, HTTPException, status
from fastapi.security import APIKeyHeader

from helper.pin_manager import state_exists, verify_active_pin

api_key = os.environ.get("PYTORRENT_API_KEY") or os.environ.get("API_PIN")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_pin_header = APIKeyHeader(name="X-API-Pin", auto_error=False)


def authenticate_request(
    request: Request,
    x_api_key: str = Security(api_key_header),
    x_api_pin: str = Security(api_pin_header),
):
    """Authenticate a request with the persisted PIN or initial environment PIN."""
    key = x_api_key or x_api_pin or request.query_params.get("key")

    if state_exists():
        if key and verify_active_pin(key):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Incorrect credentials.",
        )

    if not api_key:
        return

    if key and hmac.compare_digest(key, api_key):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access forbidden: Incorrect credentials.",
    )

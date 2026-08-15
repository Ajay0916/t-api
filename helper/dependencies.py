import os

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader, APIKeyQuery


api_key = os.environ.get("PYTORRENT_API_KEY")
api_pin = os.environ.get("API_PIN")
# PIN is OPTIONAL by default (public access works without it). Set
# API_PIN_REQUIRED=1 to force it again.
api_pin_required = os.environ.get("API_PIN_REQUIRED", "").strip().lower() in (
    "1", "true", "yes", "on",
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_pin_header = APIKeyHeader(name="X-API-Pin", auto_error=False)
api_pin_query = APIKeyQuery(name="pin", auto_error=False)


def authenticate_request(
    x_api_key: str = Security(api_key_header),
    x_api_pin: str = Security(api_pin_header),
    pin: str = Security(api_pin_query),
):
    """
    Dependency to authenticate requests. PYTORRENT_API_KEY is required when
    set (X-API-Key header). API_PIN is OPTIONAL: public requests work
    without it, and the correct pin is accepted when sent; it only blocks
    when API_PIN_REQUIRED=1 is also set (X-API-Pin header or ?pin= query).
    """
    if api_key and x_api_key != api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Incorrect credentials.",
        )
    if api_pin and api_pin_required and x_api_pin != api_pin and pin != api_pin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Incorrect PIN.",
        )

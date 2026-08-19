import os

from fastapi import Request, Security, HTTPException, status
from fastapi.security import APIKeyHeader


api_key = os.environ.get("PYTORRENT_API_KEY") or os.environ.get("API_PIN")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_pin_header = APIKeyHeader(name="X-API-Pin", auto_error=False)


def authenticate_request(
    request: Request,
    x_api_key: str = Security(api_key_header),
    x_api_pin: str = Security(api_pin_header),
):
    """Authenticate requests. Accepted (any one suffices):
    1. X-API-Key header (matches PYTORRENT_API_KEY env var)
    2. X-API-Pin header (matches PYTORRENT_API_KEY env var)
    3. key= query parameter (matches PYTORRENT_API_KEY env var)

    If PYTORRENT_API_KEY is not set, the API is fully public."""
    if not api_key:
        return
    key = x_api_key or x_api_pin or request.query_params.get("key")
    if key != api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Incorrect credentials.",
        )

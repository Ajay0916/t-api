import os

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader


api_key = os.environ.get("PYTORRENT_API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def authenticate_request(x_api_key: str = Security(api_key_header)):
    """
    Dependency to authenticate requests. When PYTORRENT_API_KEY is set,
    the X-API-Key header is required. The API is public otherwise -
    API_PIN is accepted but never enforced (optional only).
    """
    if api_key and x_api_key != api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Incorrect credentials.",
        )

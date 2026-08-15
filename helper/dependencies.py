import os

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader, APIKeyQuery


api_key = os.environ.get("PYTORRENT_API_KEY")
api_pin = os.environ.get("API_PIN")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_pin_header = APIKeyHeader(name="X-API-Pin", auto_error=False)
api_pin_query = APIKeyQuery(name="pin", auto_error=False)


def authenticate_request(
    x_api_key: str = Security(api_key_header),
    x_api_pin: str = Security(api_pin_header),
    pin: str = Security(api_pin_query),
):
    """
    Dependency to authenticate requests. When PYTORRENT_API_KEY and/or
    API_PIN env vars are set, matching credentials are required (X-API-Key
    header, X-API-Pin header or ?pin= query). Empty env = auth disabled.
    """
    if api_key and x_api_key != api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Incorrect credentials.",
        )
    if api_pin and x_api_pin != api_pin and pin != api_pin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Incorrect PIN.",
        )

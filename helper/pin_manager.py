"""Persistent API PIN storage using a salted hash."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Optional


_STATE_FILE = Path(
    os.getenv(
        "TORRENTS_PIN_STATE_FILE",
        Path(__file__).resolve().parent.parent / "pin_state.json",
    )
)
_ITERATIONS = 200_000
_cached_active_pin: Optional[str] = None


def _hash_pin(pin: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations).hex()


def state_exists() -> bool:
    return _STATE_FILE.is_file()


def _read_state() -> Optional[dict[str, Any]]:
    if not state_exists():
        return None
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if (
            data.get("version") == 1
            and data.get("algorithm") == "pbkdf2_sha256"
            and isinstance(data.get("salt"), str)
            and isinstance(data.get("pin_hash"), str)
            and isinstance(data.get("iterations"), int)
        ):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def verify_active_pin(pin: str) -> bool:
    global _cached_active_pin

    if (
        pin
        and _cached_active_pin is not None
        and hmac.compare_digest(pin, _cached_active_pin)
    ):
        return True

    state = _read_state()
    if not state:
        return False

    try:
        computed = _hash_pin(
            pin,
            bytes.fromhex(state["salt"]),
            int(state["iterations"]),
        )
        valid = hmac.compare_digest(computed, state["pin_hash"])
    except (KeyError, TypeError, ValueError):
        return False

    if valid:
        _cached_active_pin = pin
    return valid


def verify_current_pin(pin: str) -> bool:
    """Verify the rotated PIN, falling back to the bootstrap environment PIN."""
    if state_exists():
        return verify_active_pin(pin)

    initial_pin = os.environ.get("PYTORRENT_API_KEY") or os.environ.get("API_PIN") or ""
    return bool(pin and initial_pin and hmac.compare_digest(pin, initial_pin))


def set_active_pin(pin: str) -> None:
    global _cached_active_pin

    if len(pin) < 2:
        raise ValueError("PIN must be at least 2 characters")

    salt = secrets.token_bytes(16)
    record = {
        "version": 1,
        "algorithm": "pbkdf2_sha256",
        "iterations": _ITERATIONS,
        "salt": salt.hex(),
        "pin_hash": _hash_pin(pin, salt, _ITERATIONS),
    }

    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".pin_state.", dir=_STATE_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as state_file:
            json.dump(record, state_file)
            state_file.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, _STATE_FILE)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise

    _cached_active_pin = pin

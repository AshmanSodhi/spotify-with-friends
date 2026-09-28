"""In-memory stores.

PRD §12 / §29: the app must NOT store queue contents anywhere.
We store ONLY:
  - rooms: room_id / room_code / host_session_id / created_at / expires_at / status
  - host sessions: spotify access+refresh tokens (backend only, never to client)
  - guest tokens: room_id / guest_id / display_name / expires_at
  - oauth states: short-lived CSRF protection for Spotify login

Single-process in-memory storage is intentional for V1 simplicity.
For multi-instance production, swap these dicts for Redis/DB — the
access functions below are the only seam you need to change.
"""
from __future__ import annotations

import secrets
import string
import time
import uuid

# room_code -> room dict
ROOMS: dict[str, dict] = {}
# host_session_id -> {access_token, refresh_token, expires_at}
HOST_SESSIONS: dict[str, dict] = {}
# oauth state -> {host_session_id, created_at}
OAUTH_STATES: dict[str, dict] = {}
# guest_token -> {room_code, guest_id, display_name, expires_at}
GUEST_TOKENS: dict[str, dict] = {}

# Room codes avoid ambiguous chars (0/O, 1/I/L) for car readability.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
ROOM_CODE_TTL_SECONDS = 24 * 3600  # overridden per-room from settings at creation


def utc_now() -> float:
    return time.time()


def generate_room_code() -> str:
    """Short, human-readable, case-insensitive, unique among active rooms."""
    for _ in range(50):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))
        existing = ROOMS.get(code)
        if existing is None or existing["status"] != "active" or existing["expires_at"] <= utc_now():
            return code
    # Extremely unlikely fallback.
    return uuid.uuid4().hex[:CODE_LENGTH].upper()


def new_host_session_id() -> str:
    return secrets.token_urlsafe(24)


def new_guest_token() -> str:
    return secrets.token_urlsafe(24)


def new_oauth_state() -> str:
    return secrets.token_urlsafe(24)


def purge_expired() -> None:
    """Opportunistically drop expired rooms / tokens. Cheap, no background job."""
    now = utc_now()
    for code in [c for c, r in ROOMS.items() if r["expires_at"] <= now and r["status"] == "active"]:
        ROOMS[code]["status"] = "expired"
    for tok in [t for t, g in GUEST_TOKENS.items() if g["expires_at"] <= now]:
        GUEST_TOKENS.pop(tok, None)
    for st in [s for s, v in OAUTH_STATES.items() if now - v["created_at"] > 600]:
        OAUTH_STATES.pop(st, None)

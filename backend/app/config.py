"""Central configuration loaded from environment variables.

All secrets come from env — never hardcoded, never sent to the frontend.
See backend/.env.example for the full list.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Load backend/.env so local runs pick up secrets without manual $env: exports.
    # backend/app/config.py -> parents[1] = backend/, .env lives there.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:  # python-dotenv not installed; fall back to raw environment
    pass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    SPOTIFY_CLIENT_ID: str = _get("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET: str = _get("SPOTIFY_CLIENT_SECRET")
    # Must match *exactly* what is registered in the Spotify Developer Dashboard.
    SPOTIFY_REDIRECT_URI: str = _get(
        "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/spotify/callback"
    )
    # Where to send the host after OAuth completes. Same origin by default.
    FRONTEND_URL: str = _get("FRONTEND_URL", "").rstrip("/")

    SESSION_SECRET: str = _get("SESSION_SECRET") or secrets.token_hex(32)

    ROOM_TTL_HOURS: float = float(_get("ROOM_TTL_HOURS", "24") or 24)
    GUEST_TOKEN_TTL_HOURS: float = float(_get("GUEST_TOKEN_TTL_HOURS", "24") or 24)

    # Only the minimum scopes V1 needs.
    SPOTIFY_SCOPES: str = _get(
        "SPOTIFY_SCOPES", "user-modify-playback-state user-read-playback-state"
    )

    # Set MOCK_SPOTIFY=1 to run/test without real Spotify credentials.
    MOCK_SPOTIFY: bool = _get("MOCK_SPOTIFY", "").lower() in ("1", "true", "yes")

    @property
    def spotify_configured(self) -> bool:
        if self.MOCK_SPOTIFY:
            return True
        return bool(self.SPOTIFY_CLIENT_ID and self.SPOTIFY_CLIENT_SECRET)


settings = Settings()

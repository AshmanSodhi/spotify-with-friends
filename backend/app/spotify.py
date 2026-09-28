"""Spotify Web API helpers — backend only, tokens never leave the server."""
from __future__ import annotations

import base64
import re
import time
import urllib.parse

import httpx

from .config import settings

ACCOUNTS_BASE = "https://accounts.spotify.com"
API_BASE = "https://api.spotify.com/v1"

TRACK_URI_RE = re.compile(r"^spotify:track:[A-Za-z0-9]{22}$")

MOCK_TRACKS = [
    {
        "id": "0VjIjW4GlUZAMYd2vXMi3b",
        "uri": "spotify:track:0VjIjW4GlUZAMYd2vXMi3b",
        "name": "Blinding Lights",
        "artists": ["The Weeknd"],
        "album": "After Hours",
        "album_image": "https://i.scdn.co/image/ab67616d0000b2738863bc11d2aa12b54f5aeb36",
    },
    {
        "id": "4uLU6hMCjMI75M1A2tKUQm",
        "uri": "spotify:track:4uLU6hMCjMI75M1A2tKUQm",
        "name": "Never Gonna Give You Up",
        "artists": ["Rick Astley"],
        "album": "Whenever You Need Somebody",
        "album_image": "",
    },
]


def is_valid_track_uri(uri: str) -> bool:
    return bool(TRACK_URI_RE.match((uri or "").strip()))


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
        "scope": settings.SPOTIFY_SCOPES,
        "state": state,
        "show_dialog": "false",
    }
    return f"{ACCOUNTS_BASE}/authorize?" + urllib.parse.urlencode(params)


async def exchange_code_for_tokens(code: str) -> dict:
    """Trade an OAuth authorization code for access + refresh tokens."""
    if settings.MOCK_SPOTIFY:
        return {
            "access_token": "mock-access",
            "refresh_token": "mock-refresh",
            "expires_in": 3600,
        }
    auth = base64.b64encode(
        f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{ACCOUNTS_BASE}/api/token",
            headers={"Authorization": f"Basic {auth}"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
            },
        )
    if resp.status_code != 200:
        raise SpotifyAuthError(f"token exchange failed: {resp.status_code}")
    return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    if settings.MOCK_SPOTIFY:
        return {"access_token": "mock-access", "expires_in": 3600}
    auth = base64.b64encode(
        f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{ACCOUNTS_BASE}/api/token",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
    if resp.status_code in (400, 401):
        raise SpotifyReauthRequired("refresh token rejected")
    if resp.status_code != 200:
        raise SpotifyAuthError(f"refresh failed: {resp.status_code}")
    return resp.json()


async def get_valid_access_token(host_session: dict) -> str:
    """Return a non-expired access token, refreshing transparently."""
    if settings.MOCK_SPOTIFY:
        return "mock-access"
    # 60s safety margin.
    if host_session.get("access_token") and host_session.get("expires_at", 0) > time.time() + 60:
        return host_session["access_token"]
    refresh_token = host_session.get("refresh_token")
    if not refresh_token:
        raise SpotifyReauthRequired("no refresh token")
    data = await refresh_access_token(refresh_token)
    host_session["access_token"] = data["access_token"]
    host_session["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    if data.get("refresh_token"):  # Spotify sometimes rotates it
        host_session["refresh_token"] = data["refresh_token"]
    return host_session["access_token"]


async def search_tracks(access_token: str, query: str, limit: int = 10) -> list[dict]:
    if settings.MOCK_SPOTIFY:
        q = query.lower()
        if not q:
            return []
        return [t for t in MOCK_TRACKS if q in t["name"].lower() or q in " ".join(t["artists"]).lower()] or MOCK_TRACKS
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{API_BASE}/search",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"q": query, "type": "track", "limit": max(1, min(limit, 20))},
        )
    if resp.status_code == 401:
        raise SpotifyReauthRequired("access token rejected")
    if resp.status_code == 429:
        raise SpotifyApiError("Spotify is rate-limiting us, try again in a moment.")
    if resp.status_code != 200:
        raise SpotifyApiError(f"search failed ({resp.status_code})")
    items = resp.json().get("tracks", {}).get("items", [])
    out = []
    for t in items:
        images = (t.get("album") or {}).get("images") or []
        out.append(
            {
                "id": t.get("id"),
                "uri": t.get("uri"),
                "name": t.get("name"),
                "artists": [a.get("name") for a in t.get("artists", [])],
                "album": (t.get("album") or {}).get("name", ""),
                "album_image": images[0]["url"] if images else "",
            }
        )
    return out


async def add_to_queue(access_token: str, track_uri: str) -> None:
    if settings.MOCK_SPOTIFY:
        if not is_valid_track_uri(track_uri) and track_uri not in {t["uri"] for t in MOCK_TRACKS}:
            # In mock mode accept the two fixture URIs plus any well-formed URI.
            if not track_uri.startswith("spotify:track:"):
                raise SpotifyApiError("invalid track")
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{API_BASE}/me/player/queue",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"uri": track_uri},
        )
    if resp.status_code in (200, 201, 204):
        return
    if resp.status_code == 401:
        raise SpotifyReauthRequired("access token rejected")
    if resp.status_code == 404:
        # Most common cause: host has no active Spotify device.
        raise SpotifyNoActiveDevice(
            "No active Spotify device. Open Spotify on the host phone/computer and play something first."
        )
    if resp.status_code == 429:
        raise SpotifyApiError("Spotify is rate-limiting us, try again in a moment.")
    raise SpotifyApiError(f"Spotify could not add this song (status {resp.status_code}).")


async def get_current_user(access_token: str) -> dict:
    if settings.MOCK_SPOTIFY:
        return {"display_name": "Mock Host", "id": "mock-host"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API_BASE}/me", headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code == 401:
        raise SpotifyReauthRequired("access token rejected")
    if resp.status_code != 200:
        raise SpotifyApiError("could not read Spotify profile")
    return resp.json()


class SpotifyAuthError(Exception):
    pass


class SpotifyReauthRequired(Exception):
    pass


class SpotifyApiError(Exception):
    pass


class SpotifyNoActiveDevice(SpotifyApiError):
    pass

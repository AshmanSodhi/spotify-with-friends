"""Road Trip Music Requester — FastAPI backend + static frontend.

Implements PRD §14 API exactly, with the §12 constraint:
NO queue storage anywhere. Rooms hold metadata only; Spotify is the
source of truth for playback/queue.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import Cookie, FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, BadTimeSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from . import rate_limit, store
from .config import settings
from .spotify import (
    SpotifyApiError,
    SpotifyAuthError,
    SpotifyNoActiveDevice,
    SpotifyReauthRequired,
    add_to_queue,
    build_authorize_url,
    exchange_code_for_tokens,
    get_current_user,
    get_queue_state,
    get_valid_access_token,
    is_valid_track_uri,
    search_tracks,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Road Trip Music Requester")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------- models

class CreateRoomOut(BaseModel):
    room_code: str
    join_url: str


class JoinIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)


class JoinOut(BaseModel):
    guest_token: str
    room_code: str


class QueueIn(BaseModel):
    track_uri: str


# ---------------------------------------------------------------- helpers

HOST_COOKIE = "rtm_host"
OAUTH_STATE_MAX_AGE = 600
oauth_state_signer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="spotify-oauth-state")


def _err(code: str, message: str, status: int = 400):
    return JSONResponse({"error": code, "message": message}, status_code=status)


def _join_url(request: Request, code: str) -> str:
    base = settings.FRONTEND_URL or str(request.base_url).rstrip("/")
    return f"{base}/join/{code}"


def _get_room_or_error(code: str):
    store.purge_expired()
    code = (code or "").strip().upper()
    room = store.ROOMS.get(code)
    if room is None:
        return None, _err("ROOM_NOT_FOUND", "This room code doesn't exist. Check with the host.", 404)
    if room["status"] != "active" or room["expires_at"] <= store.utc_now():
        room["status"] = "expired"
        return None, _err("ROOM_EXPIRED", "This road trip room has expired.", 410)
    return room, None


def _get_host_session(host_session_id: str | None):
    if not host_session_id:
        return None
    return store.HOST_SESSIONS.get(host_session_id)


def _auth_context(
    room: dict,
    host_session_id: str | None,
    authorization: str | None,
):
    """Return (role, guest) or (None, error_response).

    Host: owns the room via host cookie. Guest: valid guest token for this room.
    """
    host = _get_host_session(host_session_id)
    if host and room["host_session_id"] == host_session_id and host.get("refresh_token"):
        return ("host", None), None
    # Guest token via `Authorization: Bearer <token>` (also accept query in GET via header fallback).
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(None, 1)[1].strip()
    if token:
        g = store.GUEST_TOKENS.get(token)
        if g and g["room_code"] == room["room_code"] and g["expires_at"] > store.utc_now():
            return ("guest", g), None
    return None, _err("GUEST_AUTH_REQUIRED", "Join the room first.", 401)


# ---------------------------------------------------------------- health

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- spotify oauth (host only)

@app.get("/api/auth/spotify/login")
def spotify_login(host_session_id: str | None = Cookie(None, alias=HOST_COOKIE)):
    if not settings.spotify_configured:
        return _err(
            "SPOTIFY_NOT_CONFIGURED",
            "Spotify credentials are not configured on the server. Set SPOTIFY_CLIENT_ID/SECRET.",
            500,
        )
    if not host_session_id or host_session_id not in store.HOST_SESSIONS:
        host_session_id = store.new_host_session_id()
        store.HOST_SESSIONS[host_session_id] = {}
    state = oauth_state_signer.dumps({"host_session_id": host_session_id})
    store.OAUTH_STATES[state] = {"host_session_id": host_session_id, "created_at": store.utc_now()}
    resp = RedirectResponse(build_authorize_url(state), status_code=302)
    resp.set_cookie(
        HOST_COOKIE, host_session_id, httponly=True, samesite="lax", max_age=30 * 24 * 3600, path="/"
    )
    return resp


@app.get("/api/auth/spotify/callback")
async def spotify_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    base = (settings.FRONTEND_URL or "/").rstrip("/") or "/"
    if error:
        return RedirectResponse(f"{base}/?spotify=denied", status_code=302)
    if not code or not state:
        return _err("INVALID_OAUTH_STATE", "Spotify login failed. Please try again.", 400)
    try:
        state_data = oauth_state_signer.loads(state, max_age=OAUTH_STATE_MAX_AGE)
    except (BadSignature, BadTimeSignature):
        return _err("INVALID_OAUTH_STATE", "Spotify login failed. Please try again.", 400)
    host_session_id = state_data.get("host_session_id")
    if not isinstance(host_session_id, str) or not host_session_id:
        return _err("INVALID_OAUTH_STATE", "Spotify login failed. Please try again.", 400)
    store.OAUTH_STATES.pop(state, None)
    try:
        tokens = await exchange_code_for_tokens(code)
    except SpotifyAuthError:
        return _err("SPOTIFY_AUTH_FAILED", "Spotify login failed. Please try again.", 502)
    store.HOST_SESSIONS[host_session_id] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
    }
    resp = RedirectResponse(f"{base}/?spotify=connected", status_code=302)
    resp.set_cookie(
        HOST_COOKIE, host_session_id, httponly=True, samesite="lax", max_age=30 * 24 * 3600, path="/"
    )
    return resp


@app.get("/api/host/spotify/status")
async def spotify_status(host_session_id: str | None = Cookie(None, alias=HOST_COOKIE)):
    host = _get_host_session(host_session_id)
    if not host or not host.get("refresh_token"):
        return {"connected": False}
    try:
        token = await get_valid_access_token(host)
        try:
            me = await get_current_user(token)
            return {"connected": True, "display_name": me.get("display_name", "")}
        except SpotifyApiError:
            return {"connected": True}
    except SpotifyReauthRequired:
        return {"connected": False, "reauth_required": True}
    except SpotifyApiError:
        return {"connected": False}


@app.post("/api/auth/spotify/disconnect")
def spotify_disconnect(host_session_id: str | None = Cookie(None, alias=HOST_COOKIE)):
    if host_session_id and host_session_id in store.HOST_SESSIONS:
        store.HOST_SESSIONS.pop(host_session_id, None)
    resp = JSONResponse({"success": True})
    resp.delete_cookie(HOST_COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- rooms

@app.post("/api/rooms", response_model=CreateRoomOut)
def create_room(request: Request, host_session_id: str | None = Cookie(None, alias=HOST_COOKIE)):
    host = _get_host_session(host_session_id)
    if not host or not host.get("refresh_token"):
        return _err("SPOTIFY_NOT_CONNECTED", "The host needs to connect Spotify.", 401)
    allowed, retry = rate_limit.check(f"create:{host_session_id}", "room_create")
    if not allowed:
        return _err("RATE_LIMITED", f"Too many rooms. Try again in {retry}s.", 429)
    store.purge_expired()
    code = store.generate_room_code()
    ttl = settings.ROOM_TTL_HOURS * 3600
    room = {
        "room_id": uuid.uuid4().hex,
        "room_code": code,
        "host_session_id": host_session_id,
        "created_at": store.utc_now(),
        "expires_at": store.utc_now() + ttl,
        "status": "active",
    }
    store.ROOMS[code] = room
    return {"room_code": code, "join_url": _join_url(request, code)}


@app.get("/api/rooms/{room_code}")
def room_info(room_code: str):
    room, err = _get_room_or_error(room_code)
    if err:
        return err
    return {"room_code": room["room_code"], "status": room["status"], "expires_at": room["expires_at"]}


@app.post("/api/rooms/{room_code}/end")
def end_room(room_code: str, host_session_id: str | None = Cookie(None, alias=HOST_COOKIE)):
    room, err = _get_room_or_error(room_code)
    if err:
        return err
    if not host_session_id or room["host_session_id"] != host_session_id:
        return _err("FORBIDDEN", "Only the host can end this room.", 403)
    room["status"] = "ended"
    room["expires_at"] = store.utc_now()
    return {"success": True}


@app.post("/api/rooms/{room_code}/join", response_model=JoinOut)
def join_room(room_code: str, body: JoinIn, request: Request):
    room, err = _get_room_or_error(room_code)
    if err:
        return err
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry = rate_limit.check(f"join:{client_ip}:{room['room_code']}", "join")
    if not allowed:
        return _err("RATE_LIMITED", f"Too many join attempts. Try again in {retry}s.", 429)
    name = body.display_name.strip()
    if not name:
        return _err("INVALID_NAME", "Please enter your name.", 400)
    token = store.new_guest_token()
    store.GUEST_TOKENS[token] = {
        "room_code": room["room_code"],
        "guest_id": uuid.uuid4().hex,
        "display_name": name[:40],
        "expires_at": store.utc_now() + settings.GUEST_TOKEN_TTL_HOURS * 3600,
    }
    return {"guest_token": token, "room_code": room["room_code"]}


# ---------------------------------------------------------------- search + queue

@app.get("/api/rooms/{room_code}/search")
async def search(
    room_code: str,
    request: Request,
    q: str = Query(default="", max_length=100),
    authorization: str | None = Header(default=None),
    host_session_id: str | None = Cookie(default=None, alias=HOST_COOKIE),
    guest_token: str | None = Query(default=None),
):
    room, err = _get_room_or_error(room_code)
    if err:
        return err
    # Allow guest token via query param (EventSource/mobile convenience) too.
    auth_header = authorization
    if not auth_header and guest_token:
        auth_header = f"Bearer {guest_token}"
    who, err = _auth_context(room, host_session_id, auth_header)
    if err:
        return err
    query = (q or "").strip()
    if not query:
        return {"tracks": []}
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry = rate_limit.check(f"search:{client_ip}:{room['room_code']}", "search")
    if not allowed:
        return _err("RATE_LIMITED", f"Too many searches. Try again in {retry}s.", 429)
    host = _get_host_session(room["host_session_id"])
    if not host or not host.get("refresh_token"):
        return _err("SPOTIFY_NOT_CONNECTED", "The host needs to connect Spotify.", 409)
    try:
        token = await get_valid_access_token(host)
        tracks = await search_tracks(token, query)
        return {"tracks": tracks}
    except SpotifyReauthRequired:
        return _err("SPOTIFY_REAUTH_REQUIRED", "The host needs to reconnect Spotify.", 409)
    except SpotifyApiError as e:
        return _err("SPOTIFY_API_ERROR", str(e) or "Spotify search failed. Try again.", 502)


@app.get("/api/rooms/{room_code}/now-playing")
async def now_playing(
    room_code: str,
    request: Request,
    authorization: str | None = Header(default=None),
    host_session_id: str | None = Cookie(default=None, alias=HOST_COOKIE),
    guest_token: str | None = Query(default=None),
):
    """Read-only live view of Spotify's queue. Nothing is stored server-side."""
    room, err = _get_room_or_error(room_code)
    if err:
        return err
    auth_header = authorization
    if not auth_header and guest_token:
        auth_header = f"Bearer {guest_token}"
    who, err = _auth_context(room, host_session_id, auth_header)
    if err:
        return err
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry = rate_limit.check(f"np:{client_ip}:{room['room_code']}", "nowplaying")
    if not allowed:
        return _err("RATE_LIMITED", f"Too many refreshes. Try again in {retry}s.", 429)
    host = _get_host_session(room["host_session_id"])
    if not host or not host.get("refresh_token"):
        return _err("SPOTIFY_NOT_CONNECTED", "The host needs to connect Spotify.", 409)
    try:
        token = await get_valid_access_token(host)
        return await get_queue_state(token)
    except SpotifyReauthRequired:
        return _err("SPOTIFY_REAUTH_REQUIRED", "The host needs to reconnect Spotify.", 409)
    except SpotifyNoActiveDevice:
        # Friendly empty state for polling UI (not an error).
        return {"currently_playing": None, "queue": [], "no_active_device": True}
    except SpotifyApiError as e:
        return _err("SPOTIFY_API_ERROR", str(e) or "Spotify is unavailable. Try again.", 502)


@app.post("/api/rooms/{room_code}/queue")
async def add_queue(
    room_code: str,
    body: QueueIn,
    request: Request,
    authorization: str | None = Header(default=None),
    host_session_id: str | None = Cookie(default=None, alias=HOST_COOKIE),
):
    room, err = _get_room_or_error(room_code)
    if err:
        return err
    who, err = _auth_context(room, host_session_id, authorization)
    if err:
        return err
    uri = (body.track_uri or "").strip()
    if not is_valid_track_uri(uri):
        return _err("INVALID_TRACK", "The selected Spotify track is invalid.", 400)
    key = who[1]["guest_id"] if who[0] == "guest" else f"host:{host_session_id}"
    allowed, retry = rate_limit.check(f"queue:{key}:{room['room_code']}", "queue")
    if not allowed:
        return _err("RATE_LIMITED", f"Whoa, slow down! Try again in {retry}s.", 429)
    host = _get_host_session(room["host_session_id"])
    if not host or not host.get("refresh_token"):
        return _err("SPOTIFY_NOT_CONNECTED", "The host needs to connect Spotify.", 409)
    try:
        token = await get_valid_access_token(host)
        try:
            await add_to_queue(token, uri)
        except SpotifyReauthRequired:
            # One transparent retry after refresh.
            token = await get_valid_access_token(host)
            await add_to_queue(token, uri)
        # NOTE: deliberately no persistence of the track — Spotify owns the queue.
        return {"success": True, "message": "Added to Spotify queue"}
    except SpotifyReauthRequired:
        return _err("SPOTIFY_REAUTH_REQUIRED", "The host needs to reconnect Spotify.", 409)
    except SpotifyNoActiveDevice as e:
        return _err("SPOTIFY_NO_DEVICE", str(e), 409)
    except SpotifyApiError:
        return _err(
            "SPOTIFY_API_ERROR",
            "Spotify could not add this song right now. Please try again.",
            502,
        )


# ---------------------------------------------------------------- frontend pages

@app.get("/", include_in_schema=False)
def index_page():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/join/{room_code}", include_in_schema=False)
def join_page(room_code: str):
    # Same SPA handles /join/:code — normalise code server-side for safety.
    return FileResponse(str(STATIC_DIR / "room.html"))


@app.get("/room/{room_code}", include_in_schema=False)
def room_page(room_code: str):
    return FileResponse(str(STATIC_DIR / "room.html"))

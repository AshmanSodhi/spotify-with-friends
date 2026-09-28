"""End-to-end API tests with mocked Spotify (MOCK_SPOTIFY=1).

Covers PRD §26 acceptance: health, room lifecycle, join, search,
queue add, error codes, and the no-queue-storage constraint.
"""
import os

os.environ["MOCK_SPOTIFY"] = "1"

from fastapi.testclient import TestClient

from backend.app import main, rate_limit
from backend.app import store


def make_client():
    store.ROOMS.clear()
    store.HOST_SESSIONS.clear()
    store.GUEST_TOKENS.clear()
    store.OAUTH_STATES.clear()
    rate_limit.reset()
    return TestClient(main.app)


def seed_host():
    """Pretend the host already finished Spotify OAuth."""
    sid = store.new_host_session_id()
    store.HOST_SESSIONS[sid] = {
        "access_token": "mock-access",
        "refresh_token": "mock-refresh",
        "expires_at": 9999999999,
    }
    return sid


def test_health():
    c = make_client()
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_full_flow():
    c = make_client()
    sid = seed_host()

    # create room
    r = c.post("/api/rooms", cookies={"rtm_host": sid})
    assert r.status_code == 200, r.text
    code = r.json()["room_code"]
    assert len(code) == 6

    # room info
    r = c.get(f"/api/rooms/{code}")
    assert r.status_code == 200

    # guest join
    r = c.post(f"/api/rooms/{code}/join", json={"display_name": "Rahul"})
    assert r.status_code == 200, r.text
    token = r.json()["guest_token"]

    # search
    r = c.get(f"/api/rooms/{code}/search?q=blinding", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    tracks = r.json()["tracks"]
    assert tracks and tracks[0]["uri"].startswith("spotify:track:")

    # add to queue — valid
    r = c.post(
        f"/api/rooms/{code}/queue",
        json={"track_uri": tracks[0]["uri"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True

    # add to queue — invalid URI rejected, nothing stored
    r = c.post(
        f"/api/rooms/{code}/queue",
        json={"track_uri": "not-a-uri"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_TRACK"

    # constraint: no queue data persisted anywhere server-side
    assert not any("queue" in k.lower() for k in store.ROOMS.get(code, {}))
    for room in store.ROOMS.values():
        assert "queue" not in room

    # unauthenticated search rejected
    r = c.get(f"/api/rooms/{code}/search?q=x")
    assert r.status_code == 401

    # end room, then joins rejected
    r = c.post(f"/api/rooms/{code}/end", cookies={"rtm_host": sid})
    assert r.status_code == 200
    r = c.post(f"/api/rooms/{code}/join", json={"display_name": "Late"})
    assert r.status_code == 410
    assert r.json()["error"] == "ROOM_EXPIRED"


def test_create_room_requires_spotify():
    c = make_client()
    r = c.post("/api/rooms")
    assert r.status_code == 401
    assert r.json()["error"] == "SPOTIFY_NOT_CONNECTED"


def test_now_playing_view():
    c = make_client()
    sid = seed_host()
    r = c.post("/api/rooms", cookies={"rtm_host": sid})
    code = r.json()["room_code"]
    r = c.post(f"/api/rooms/{code}/join", json={"display_name": "Rahul"})
    token = r.json()["guest_token"]

    r = c.get(
        f"/api/rooms/{code}/now-playing", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currently_playing"]["uri"].startswith("spotify:track:")
    assert isinstance(body["queue"], list)

    # unauthenticated view rejected
    r = c.get(f"/api/rooms/{code}/now-playing")
    assert r.status_code == 401

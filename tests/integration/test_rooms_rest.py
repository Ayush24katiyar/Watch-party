"""REST integration tests: identity and rooms (architecture 8.1, 16 Phase 2)."""

import pytest

from tests.conftest import TEST_ORIGIN  # noqa: F401  (documents the shared origin)


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from watch_party.config import get_settings
    from watch_party.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def auth_headers(user_id: str, token: str) -> dict[str, str]:
    return {"X-User-Id": user_id, "X-User-Token": token}


def test_create_user_returns_identity(client) -> None:
    response = client.post("/api/users")
    assert response.status_code == 201
    body = response.json()
    assert body["userId"] and body["token"]


def test_create_room_returns_code(client) -> None:
    identity = client.post("/api/users").json()
    response = client.post("/api/rooms", headers=auth_headers(identity["userId"], identity["token"]))
    assert response.status_code == 201
    code = response.json()["code"]
    assert len(code) == 6
    assert set(code) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")


def test_create_room_with_bad_token_is_unauthorized(client) -> None:
    identity = client.post("/api/users").json()
    response = client.post("/api/rooms", headers=auth_headers(identity["userId"], "nope"))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


def test_create_room_without_headers_is_unauthorized(client) -> None:
    response = client.post("/api/rooms")
    assert response.status_code == 401


def test_check_room_after_creation(client) -> None:
    identity = client.post("/api/users").json()
    code = client.post("/api/rooms", headers=auth_headers(identity["userId"], identity["token"])).json()[
        "code"
    ]
    response = client.get(f"/api/rooms/{code}")
    assert response.status_code == 200
    body = response.json()
    assert body["joinable"] is True
    assert body["code"] == code


def test_check_room_is_case_insensitive(client) -> None:
    identity = client.post("/api/users").json()
    code = client.post("/api/rooms", headers=auth_headers(identity["userId"], identity["token"])).json()[
        "code"
    ]
    response = client.get(f"/api/rooms/{code.lower()}")
    body = response.json()
    assert body["joinable"] is True
    assert body["code"] == code  # stored (upper) code returned


def test_check_unknown_room_reports_not_found(client) -> None:
    body = client.get("/api/rooms/NOSUCH").json()
    assert body["joinable"] is False
    assert body["reason"] == "not_found"


def test_room_limit_per_user(client, monkeypatch) -> None:
    from watch_party.config import get_settings

    monkeypatch.setenv("MAX_LIVE_ROOMS_PER_USER", "2")
    get_settings.cache_clear()
    identity = client.post("/api/users").json()
    headers = auth_headers(identity["userId"], identity["token"])
    assert client.post("/api/rooms", headers=headers).status_code == 201
    assert client.post("/api/rooms", headers=headers).status_code == 201
    response = client.post("/api/rooms", headers=headers)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "room_limit"

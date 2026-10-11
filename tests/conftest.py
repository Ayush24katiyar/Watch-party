"""Pytest configuration (root: shared by unit + integration).

DB-touching fixtures live in `tests/integration/conftest.py` so that
`uv run pytest tests/unit` passes with Postgres stopped. Everything here is
DB-free: env forcing, wire helpers with deadlines, and small test utilities.
"""

import os

# Forced assignment (not setdefault): a developer's shell must not change test config.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://watch:watch@127.0.0.1:5432/watchparty_test"
# Same engine is used from several event loops in tests -> no pooled connections.
os.environ["DB_NULL_POOL"] = "true"
# Fast, deterministic WebSocket settings for tests (architecture values /10).
os.environ["JOIN_TIMEOUT_SECONDS"] = "0.3"
os.environ["WS_PING_INTERVAL_SECONDS"] = "0.2"
os.environ["WS_PING_TIMEOUT_SECONDS"] = "0.5"
os.environ["WS_RATE_LIMIT_OTHER_PER_SECOND"] = "5"
# Normal join payloads are ~170-195 bytes; 1024 keeps headroom while the
# oversized-message test sends 2000 bytes (see test_ws_foundation.py).
os.environ["WS_MAX_SIZE_BYTES"] = "1024"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173"
os.environ["ALLOW_MISSING_ORIGIN"] = "false"

import concurrent.futures
import time

TEST_ORIGIN = "http://localhost:5173"

# A TestClient receive blocks forever if the server never sends/closes; bound it
# so a regression shows up as a failed test instead of a hung suite.
RECEIVE_TIMEOUT_SECONDS = 10.0


def join_payload(room_code: str, user_id: str, token: str, username: str = "player") -> dict:
    return {
        "type": "join_room",
        "payload": {
            "roomId": room_code,
            "username": username,
            "userId": user_id,
            "token": token,
        },
    }


def error_of(websocket) -> dict:
    """Next `error` event payload, answering pings on the way."""
    return recv_until(websocket, lambda e: e.get("type") == "error")["payload"]


def participant_by_id(participants, user_id: str) -> dict:
    """Single participant row by user id (fails clearly instead of IndexError)."""
    for participant in participants:
        if participant["userId"] == user_id:
            return participant
    raise AssertionError(f"participant {user_id} not in {[p['userId'] for p in participants]}")


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.05):
    """Poll `predicate()` until truthy; raise with a clear message on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        time.sleep(interval)


class FakeClock:
    """Injectable clock for TokenBucket / time-dependent unit tests (no sleeping)."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def receive_json_bounded(websocket, timeout: float = RECEIVE_TIMEOUT_SECONDS) -> dict:
    """receive_json that fails instead of hanging if nothing ever arrives."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(websocket.receive_json)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise AssertionError(f"no server message within {timeout}s") from exc
    finally:
        # wait=False: the worker may be blocked in receive_json; do not let
        # pool teardown re-introduce the hang this helper exists to prevent.
        pool.shutdown(wait=False, cancel_futures=True)


def receive_pings(websocket, count: int) -> None:
    """Wait for `count` server pings, answering each with pong (10.6).

    Cannot use recv_until: that helper consumes pings, so waiting *for* a ping
    would never return.
    """
    for _ in range(count):
        while True:
            event = receive_json_bounded(websocket)
            if event.get("type") == "ping":
                break
        websocket.send_json({"type": "pong", "payload": {}})


def recv_until(websocket, predicate, timeout: float = RECEIVE_TIMEOUT_SECONDS):
    """Receive server events, answering pings, until `predicate(event)` matches.

    Has an overall deadline: steady pings must not mask a missing event forever.
    On expiry raises AssertionError listing the event types seen.
    """
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while True:
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"event not received within {timeout}s; saw event types: {seen or ['<none>']}"
            )
        remaining = deadline - time.monotonic()
        try:
            event = receive_json_bounded(websocket, timeout=min(timeout, remaining))
        except AssertionError:
            continue  # slice expired without a message; loop top reports the deadline
        if event.get("type") == "ping":
            websocket.send_json({"type": "pong", "payload": {}})
            continue
        seen.append(str(event.get("type")))
        if predicate(event):
            return event


def drain_until_close(websocket):
    """Consume events (ignoring pings) until the server closes the socket."""
    while True:
        websocket.receive_text()

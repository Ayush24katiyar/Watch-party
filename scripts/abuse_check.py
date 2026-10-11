"""Abuse / security checks (architecture 18.3) - run against a live dev server.

Usage: start `uv run fastapi dev`, then `uv run python scripts/abuse_check.py`.
Each check prints PASS/FAIL; exit code is 0 only if all pass.
"""

import json
import sys
import urllib.request

import anyio
from websockets.sync.client import connect

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
ORIGIN = {"Origin": "http://localhost:5173"}

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}: {name}{(' - ' + detail) if detail else ''}")


def post(path: str, headers=None):
    request = urllib.request.Request(BASE + path, method="POST", headers=headers or {})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def next_event(ws, type_=None, timeout=3.0):
    import time

    deadline = time.monotonic() + timeout
    while True:
        message = json.loads(ws.recv(timeout=deadline - time.monotonic()))
        if type_ is None or message["type"] == type_:
            return message


async def main() -> None:
    host = post("/api/users")
    guest = post("/api/users")
    room = post("/api/rooms", {"X-User-Id": host["userId"], "X-User-Token": host["token"]})
    code = room["code"]

    # 1. Silent socket -> closed 4007 after the join timeout.
    try:
        with connect(f"{WS}/ws/{code}", additional_headers=ORIGIN) as ws:
            ws.recv(timeout=5)
        check("silent socket closed 4007", False, "no disconnect")
    except Exception as exc:
        check("silent socket closed 4007", "4007" in str(exc) or "4007" in repr(exc), str(exc)[:80])

    # 2. Participant change_video -> forbidden.
    host_ws = connect(f"{WS}/ws/{code}", additional_headers=ORIGIN)
    guest_ws = connect(f"{WS}/ws/{code}", additional_headers=ORIGIN)
    for ws, user, name in ((host_ws, host, "ayush"), (guest_ws, guest, "neha")):
        ws.send(json.dumps({"type": "join_room", "payload": {"roomId": code, "username": name, "userId": user["userId"], "token": user["token"]}}))
        next_event(ws, "room_joined")
    guest_ws.send(json.dumps({"type": "change_video", "payload": {"videoId": "dQw4w9WgXcQ"}}))
    error = next_event(guest_ws, "error")["payload"]
    check("participant change_video forbidden", error["code"] == "forbidden", error["code"])

    # 3. Oversized message -> closed.
    try:
        guest_ws.send(json.dumps({"type": "chat", "payload": {"text": "x" * 2000}}))
        next_event(guest_ws, "error")
        guest_ws.recv(timeout=3)
        check("oversized message closed 4007", False, "no disconnect")
    except Exception as exc:
        check("oversized message closed 4007", "4007" in str(exc) or "4007" in repr(exc), str(exc)[:80])

    # 4. Wrong Origin -> rejected before accept.
    try:
        with connect(f"{WS}/ws/{code}", additional_headers={"Origin": "http://evil.com"}) as ws:
            ws.recv(timeout=3)
        check("wrong origin rejected", False, "no denial")
    except Exception:
        check("wrong origin rejected", True)

    # 5. Chat roundtrip + persistence in room_joined.
    host_ws.send(json.dumps({"type": "chat", "payload": {"text": "hello room"}}))
    chat = next_event(guest_ws, "chat_message")["payload"]
    check("chat broadcast", chat["text"] == "hello room" and chat["username"] == "ayush")
    host_ws.close()
    guest_ws.close()

    host_ws = connect(f"{WS}/ws/{code}", additional_headers=ORIGIN)
    host_ws.send(json.dumps({"type": "join_room", "payload": {"roomId": code, "username": "ayush", "userId": host["userId"], "token": host["token"]}}))
    joined = next_event(host_ws, "room_joined")["payload"]
    check("recentChat replayed", any(m["text"] == "hello room" for m in joined["recentChat"]))
    host_ws.close()

    # 6. Reaction allow-list.
    guest_ws = connect(f"{WS}/ws/{code}", additional_headers=ORIGIN)
    guest_ws.send(json.dumps({"type": "join_room", "payload": {"roomId": code, "username": "neha", "userId": guest["userId"], "token": guest["token"]}}))
    next_event(guest_ws, "room_joined")
    guest_ws.send(json.dumps({"type": "reaction", "payload": {"emoji": "🚀"}}))
    error = next_event(guest_ws, "error")["payload"]
    check("reaction allow-list enforced", error["code"] == "invalid_message", error["code"])
    guest_ws.close()


if __name__ == "__main__":
    anyio.run(main)
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)

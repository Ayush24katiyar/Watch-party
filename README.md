# Watch Party

Watch together, from anywhere. Watch Party lets a group watch the same
YouTube video in perfect sync from different browsers — one room, one clock,
with roles, approval requests, chat, and reactions built in.

## Setup & run (local)

Prerequisites: Docker, `uv`, Node 20+.

```bash
# 1. Backend config
cp .env.example .env

# 2. Database (Postgres 16) + schema
docker compose up -d
uv run alembic upgrade head

# 3. Backend — http://localhost:8000
uv run fastapi dev

# 4. Frontend — http://localhost:5173 (new terminal)
cd client
npm install
npm run dev
```

Open `http://localhost:5173`, pick a display name, create a room, and open
the room link in a second tab or send the 6-character code to a friend.

Useful commands:

```bash
uv run pytest              # full backend suite (needs the DB from step 2)
uv run pytest tests/unit   # pure unit tests, no infrastructure needed
cd client && npm run build # type-check + production bundle into client/dist/
cd client && npx oxlint    # frontend lint
```

## How it works

One user creates a room and becomes **host**; others join by code. Playback
is server-driven: the backend owns the video position and broadcasts a
versioned `sync_state` stream (sequence numbers, drift correction, reconnect
rejoin), so play, pause, seeks, and video changes land on every screen
together — including late joiners, who get the position advanced to now.

Rooms have **roles**. The host promotes moderators, kicks members (kicked
users can't rejoin), transfers hosting, and locks the room. Participants
can't touch playback directly; they send **approval requests** the host or a
moderator accepts or rejects. Rooms also have **live chat** (persisted and
replayed on join) and ephemeral emoji **reactions**.

If the network drops, the client backs off and reconnects, then replays
`join_room` automatically and resyncs — no manual refresh dance.

## Technology

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (Python 3.13) | Async-native, Pydantic validation on every message |
| Realtime | Native WebSockets (no Socket.IO) | Full control over close codes, heartbeat, and backpressure |
| Frontend | React 19 + Vite + TypeScript | Component UI over a single socket hook + reducer |
| Player | YouTube IFrame API | Custom controls, echo guard, 2 s drift check |
| Database | PostgreSQL 16 via Docker | Durable rooms, members, chat, playback snapshots |
| DB access | SQLAlchemy 2 async + asyncpg, Alembic migrations | One repository layer owns all SQL; migrations version the schema |
| Auth | Anonymous UUID + token | No signup; SHA-256 hashes stored, constant-time compare, token shown once |
| Tests | pytest + pytest-asyncio (174 tests, 87% branch coverage) | Real TestClient sockets against a dedicated test DB |
| Tooling | `uv`, Docker Compose, pytest-timeout, oxlint + `tsc`, jscpd | Fast installs, hang-proof suite, linted client |

Key design points: single-instance server with in-memory room state
(Postgres holds the durable snapshot plus a stale-room reaper), per-room
locks, per-connection rate-limit buckets, server-side permission checks on
every privileged action, heartbeats with zombie detection, and structured
logging that never records tokens or message content.

## Deploying

**Backend (Render web service, repo root):** build
`pip install uv && uv sync --frozen`, start
`alembic upgrade head && uv run fastapi run --host 0.0.0.0 --port $PORT`.
Set `DATABASE_URL` (convert Render's `postgres://` to
`postgresql+asyncpg://`), `ALLOWED_ORIGINS` to the frontend URL, and
`ALLOW_MISSING_ORIGIN=false`.

**Frontend (Vercel static site, root directory `client`):** build
`npm run build`, output `dist`. Set `VITE_API_URL` (https) and `VITE_WS_URL`
(wss) to the backend — Vite bakes these in at build time, so redeploy after
changing them.

## Testing notes

* `pyproject.toml` sets a global `timeout = 30` (thread method) plus
  `faulthandler_timeout = 20`, so a hung test fails instead of freezing the suite.
* Every wait in `tests/conftest.py` has a deadline and raises `AssertionError`
  with a clear message (no silent hangs).
* DB fixtures live in `tests/integration/` only. The suite is serial-only
  (shared test DB) — never overlap two runs.
* Verbose debugging: `uv run pytest -x -s -v --timeout=15`.

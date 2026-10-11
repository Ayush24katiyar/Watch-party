# Watch Party

Real-time YouTube watch party with WebSocket sync (FastAPI + React + Postgres).

## Testing

Requires Docker for the integration suite (Postgres test DB):

```bash
docker compose start   # test DB (watchparty_test on 127.0.0.1:5432)
uv run pytest
```

Verbose single run with a tight timeout (hangs fail with a thread dump):

```bash
uv run pytest -x -s -v --timeout=15
```

Unit tests need no infrastructure:

```bash
uv run pytest tests/unit   # passes with Docker stopped
```

Notes:

- `pyproject.toml` sets a global `timeout = 30` (`thread` method) plus a
  `faulthandler_timeout = 20`, so a hung test fails instead of freezing the suite.
- Every wait in `tests/conftest.py` (`receive_json_bounded`, `recv_until`,
  `wait_until`) has a deadline and raises `AssertionError` with a clear message.
- DB fixtures (`migrated_test_database`, `clean_state`) are scoped to
  `tests/integration/` only.

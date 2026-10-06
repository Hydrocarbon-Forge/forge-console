# Insights Board — Hydrocarbon Forge

Standalone, always-local usage board for the Hermes instance. Pure SQL over
the local Hermes state DB plus a hand-maintained `pricing.json` overlay.
No LLM calls, no network fetches from the backend.

## Run

```sh
python3 server.py --port 8901
# open http://0.0.0.0:8901/
```

Flags (all optional):

- `--host 0.0.0.0` (default; LAN-hosted by project convention)
- `--port 8901`
- `--db ~/.hermes/state.db` (or env `HERMES_DB`)

Backend is Python 3 stdlib only (`ThreadingHTTPServer` + `sqlite3`, DB opened
read-only `mode=ro`). Frontend is static `web/` (no build, no npm).

## Endpoints

- `GET /api/summary?days=7|30|90|365|all` (canonical; `GET /api/insights?days=…`
  is a documented alias, identical payload)
- `GET /api/models?days=…` (residual-folded per-model breakdown)
- `GET /api/platforms?days=…`
- `GET /api/tools?days=…` (reconciled per session/tool max)
- `GET /api/skills?days=…`
- `GET /api/activity?days=…` (includes `tools` top-20 + `tools_total` for the window)
- `GET /api/cost?days=…` (pricing.json overlay)
- `GET /api/health`
- `GET /api/pricing` / `POST /api/pricing` (atomic tmp+rename write)

Each data endpoint returns `{"generated_at","db_mtime","days",…}` and accepts
`?days=` (default 30). Aggregates refresh when `state.db` mtime changes or
after 60s TTL.

## Pricing

`pricing.json` shape:

```json
{"models": {"<model-id>": {"input": 0.4, "output": 1.6, "cache_read": 0.04,
  "cache_write": 0.5, "note": "...", "also": ["alias"]}}}
```

Rates are $/M tokens. Matching is case-insensitive on the full id and any
`also` alias, after lowercasing + basename + provider-prefix stripping.

Edit via UI (EDIT PRICES) or curl:

```sh
curl -s -X POST localhost:8901/api/pricing \
  -d '{"models": {"qwen-3.8-27b": {"input":0.4,"output":1.6,"cache_read":0.04}}}'
```

## Tests

```sh
python3 server.py --port 8901 &
python3 test_api.py            # or: python3 test_api.py --port 8901
```

Checks shapes + spec invariants (sessions/tokens, top model, terminal first,
24×30 activity, cost unpriced→priced, static brand, DB mtime).

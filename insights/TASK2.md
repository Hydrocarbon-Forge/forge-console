# Task 2 — harden + reconcile (muse-spark-1.3 xhigh)

Context: v1 is built, committed (3e8fa63), and serving at 127.0.0.1:8901. An independent
verifier (`verify_c6.py`, written by C6 — do NOT delete it, fix the code so it passes)
found 3 issues. The pricing overlay was replaced with 20 sourced models (official
2026-10 rates: Anthropic platform docs, OpenAI developers.openai.com, Google
ai.google.dev, DeepSeek api-docs) — the server must keep working with the new file.

Do ALL of the following, in this directory, stdlib-only constraints unchanged
(no pip, no LLM calls from the backend, DB opened read-only, bind 127.0.0.1):

1. **Drift-proof the test suite.** `test_api.py` failed 2/44 because its fixed
   expected values (cache_read ~10,017,655 / total ~11,400,165) predate live
   Hermes writes. Make the drift checks robust: capture a baseline from the
   endpoint itself (or the DB read-only) at run start, assert monotonicity +
   plausibility (e.g. >= baseline, < 3x baseline, cache_read < total), never a
   hardcoded snapshot. Suite must go 44/44 and STAY green while the DB is live.

2. **Fix the empty 7-day tool breakdown.** `GET /api/activity?days=7` returns
   `tools: []` while `?days=30` returns real data (terminal 267, read_file 30, ...).
   Inspect the SQL — likely the window filter is applied to session start times
   while tool usage is aggregated per-session, so recent sessions started within
   the window may be excluded or the join drops rows. Root-cause, fix, verify
   `tools` is non-empty for days=7 AND days=1, and that counts for days=7 are a
   subset-consistent of days=30 (<= per tool).

3. **Reconcile spec vs implementation routes.** SPEC.md lists `/api/insights`
   but the server implements `/api/summary` (the frontend uses /api/summary and
   is consistent with the other 7 routes). Pick ONE canonical name — prefer
   keeping `/api/summary` as the implementation, ADD `/api/insights` as a
   documented alias (cheap, keeps old spec/tests working), and update SPEC.md's
   endpoint table so spec, server, frontend, test_api.py, and verify_c6.py all
   agree. Update the README endpoint table too.

4. **Prove the new pricing overlay works end-to-end.** With the 20-model
   pricing.json: `GET /api/cost` must show `priced:false` for qwen-3.8-27b (no
   entry), and a temporary test entry added via `POST /api/pricing` for
   qwen-3.8-27b (input 0.4, output 1.6, cache_read 0.04) must yield cost > 0
   and plausible magnitude for 30d (~$1–3). Restore the file to the 20-model
   state afterward (the file on disk is the source of truth; `GET /api/pricing`
   must reflect it verbatim + generated_at).

5. **Full green run.** Start/keep the server on 8901, then run BOTH
   `python3 test_api.py` (expect 44/44) AND `python3 verify_c6.py` (expect 19/19)
   with real output pasted. Verify `state.db` mtime is unchanged across the run.

6. Commit everything (git) with a message "task2: drift-proof tests, fix 7d tool
   window, route alias, pricing end-to-end".

Report: files changed, the two test-suite outputs verbatim, the SQL you fixed and
why, and any deviations.

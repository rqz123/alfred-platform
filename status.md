# Alfred Platform - Shared Dev/Test Status

STATUS: test_passed
LAST_UPDATED: 2026-05-10 21:59 PDT
MILESTONE: PRD-v0.9 / M6
BRANCH: main
CODEX_TEST_OUTPUT: M6 focused verification passed

## CURRENT_TASK
M6 verification complete. Docker intentionally not tested.

## CLAUDE_DEV_OUTPUT
M6 changes under test:
- `services/brain/services/trigger_monitor.py`: fixed NameError by moving `logger.info("Expired thread …")` into `_handle_expiry`.
- `services/thread/routers/thread.py`: added API-key-authenticated `GET /alfred/threads?user_phone=<phone>` for Brain.
- `services/brain/services/proactive_nudge.py`: `_get_idle_threads` now calls `/alfred/threads`; `_discover_users` reads from `persona_profiles`.
- `services/gateway/app/services/account_bot_service.py`: `_cmd_family_add` calls fire-and-forget `_init_persona(...)` to create PersonaProfile rows in Brain.

## CODEX_TEST_OUTPUT
Test mode: local venv services only; Docker skipped.
Services started for test: Thread 8002 and Brain 8003.
Services stopped after test; ports 8002 and 8003 are clean.

Passed:
- Python compile check passed for the 4 touched files.
- Brain service started successfully and ran trigger expiry logic without NameError.
- Expiry logging now executes inside `_handle_expiry`; observed `Expired thread ...` log lines during Brain startup.
- Thread internal endpoint `GET /api/thread/alfred/threads?user_phone=<phone>`:
  - Missing key rejected with 401.
  - Bad key rejected with 401.
  - Valid `X-Alfred-API-Key` returned 200.
  - Returned active threads only for the requested `triggerSource`.
  - Excluded archived threads and other users' threads.
  - Response fields were limited to `id`, `title`, `content`, `createdAt`, `updatedAt`.
- Brain proactive nudge:
  - `_discover_users()` found a test user from `persona_profiles`.
  - `_get_idle_threads(user_phone)` successfully fetched an old idle thread via the new Thread internal endpoint.
- Brain persona endpoint used by Gateway `_init_persona`:
  - Bad key returns 403.
  - Missing required fields returns 422.
  - Valid create returns 204.
  - Repeated create is idempotent; row count remains 1.

Notes:
- Gateway `_init_persona` was verified statically: `_cmd_family_add` calls it after `repo.update_user(...)`, and `_init_persona` posts to `${BRAIN_URL}/api/brain/personas` with `X-Alfred-API-Key`.
- No full wa-sim regression was run because M6 touched internal Thread/Brain/Gateway wiring rather than WhatsApp user flows.

# Alfred Platform - Shared Dev/Test Status

STATUS: test_passed
LAST_UPDATED: 2026-05-14 09:35 PDT
MILESTONE: Settings / Alfred Bot connection UX
BRANCH: main

## CURRENT_TASK
Round 8 clean retest: verify Bot Reconnect is non-destructive and Forget Device is destructive using the updated Bridge process.

## CLAUDE_DEV_OUTPUT
Fixed `bridge/src/server.mjs` for Chrome profile recreation race:
- Added `_deletingSet` guard.
- Kill Chrome before waiting on in-flight init for destructive delete.
- Added retry-verified auth profile wipe.
- DELETE returns failure if profile cannot be cleaned.

## CODEX_TEST_OUTPUT
Result: PASS after killing a stale orphan Bridge process and restarting the stack cleanly.

Verified:
- Gateway syntax check passed for `services/gateway/app/api/routes.py` and `services/gateway/app/services/bridge_service.py`.
- Bridge syntax check passed for `bridge/src/server.mjs`.
- Web build passed.
- Local stack is healthy: Gateway, OurCents, Thread, Brain, Bridge.
- Actual Bridge listener after clean restart: PID 13766 on port 3001.

Runtime test:
- Created a fresh Gateway connection.
- Inserted a marker file into `.wwebjs_auth/session-855544e9-d59b-427e-b495-16a35701123c`.
- Called Reconnect/Restart via Gateway.
- Marker survived restart: PASS.
- Called Forget Device via Gateway.
- DELETE returned HTTP 204.
- Auth dir after delete: absent.
- Bridge `/sessions`: deleted session not listed.
- Host process check: zero Chromium processes using that auth profile.

Bridge log confirms the intended new path executed:
- `Late init error on deleting session — cleaning up`
- `Session destroyed + auth wiped`

Residual issue found during retest setup:
- An old orphan Bridge process from the previous run was still listening on port 3001 as PID 4268, while `.logs/bridge.pid` pointed elsewhere.
- `start.sh` initially reported healthy because it hit that old process, while the new Bridge failed with `EADDRINUSE`.
- This can make future tests accidentally hit stale code.
- Recommended follow-up: make `start.sh`/`stop.sh` detect and handle existing listeners on managed ports, or verify that the listening PID matches the PID just started.

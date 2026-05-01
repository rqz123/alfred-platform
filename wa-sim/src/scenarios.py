"""
Scenario loader and runner.

Public API
----------
load_scenarios()       → list[dict]
scenarios_by_group()   → dict[str, list[dict]]
pick_scenario()        → dict   (random weighted, optionally filtered by group/name)
run_scenario()         → bool   (True = all steps passed)
run_group()            → dict   (summary for one group)
"""

import asyncio
import random
from pathlib import Path
from typing import Any

import yaml

from . import gateway_client, ui
from . import error_log
from .bridge_mock import get_reply_queue
from . import settings

REPLY_TIMEOUT = 30.0   # seconds per step
CONFIG_PATH = Path(__file__).parent.parent / "config" / "scenarios.yaml"


# ── Loaders ────────────────────────────────────────────────────────

def load_scenarios() -> list[dict[str, Any]]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("scenarios", [])


def scenarios_by_group(scenarios: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return scenarios keyed by group name."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in scenarios:
        g = s.get("group", "ungrouped")
        groups.setdefault(g, []).append(s)
    return groups


def pick_scenario(
    scenarios: list[dict[str, Any]],
    name: str | None = None,
    group: str | None = None,
) -> dict[str, Any]:
    pool = scenarios
    if group:
        pool = [s for s in pool if s.get("group") == group]
    if name:
        for s in pool:
            if s["name"] == name:
                return s
        raise ValueError(f"Scenario '{name}' not found (group={group})")
    if not pool:
        raise ValueError(f"No scenarios for group={group}")
    weights = [s.get("weight", 1) for s in pool]
    return random.choices(pool, weights=weights, k=1)[0]


# ── Single-scenario runner ─────────────────────────────────────────

async def run_scenario(
    scenario: dict[str, Any],
    session_id: str | None = None,
    phone_names: dict[str, str] | None = None,
) -> bool:
    """
    Run all steps of a scenario.  Returns True if every step passed.
    Logs each step result to error_log.
    """
    steps = scenario.get("steps", [])
    sid = session_id or settings.SESSION_ID
    group = scenario.get("group", "ungrouped")
    total_steps = len(steps)
    failed_steps = 0

    # Discard stale replies for any phone used in this scenario before starting.
    scenario_phones = {step["phone"] for step in steps}
    await _drain_replies(scenario_phones)

    for i, step in enumerate(steps, 1):
        phone: str = step["phone"]
        body: str = step["send"]
        name: str = (phone_names or {}).get(phone, phone)
        expect: str | None = step.get("expect_contains")
        no_wait: bool = step.get("no_wait", False)
        pause: float = step.get("pause", 0.0)
        timeout: float = step.get("timeout", REPLY_TIMEOUT)

        if pause > 0:
            await asyncio.sleep(pause)

        ui.log_scenario(scenario["name"], i, total_steps)
        ui.log_sent(phone, body)

        # Send message — one automatic retry after 2 s for transient errors
        send_exc: Exception | None = None
        for attempt in range(2):
            try:
                await gateway_client.send_message(phone, name, body, session_id=sid)
                send_exc = None
                break
            except Exception as exc:
                send_exc = exc
                if attempt == 0:
                    ui.log_error(f"Send error (retrying): {type(exc).__name__}: {exc}")
                    await asyncio.sleep(2)

        if send_exc is not None:
            detail = f"{type(send_exc).__name__}: {send_exc}" or type(send_exc).__name__
            ui.log_error(f"Send failed: {detail}")
            error_log.log_result(
                scenario=scenario["name"], group=group, step=i,
                phone=phone, sent=body, reply=None,
                status="send_error", expect_contains=expect, error_detail=detail,
            )
            failed_steps += 1
            continue

        if no_wait:
            error_log.log_result(
                scenario=scenario["name"], group=group, step=i,
                phone=phone, sent=body, reply=None,
                status="pass", expect_contains=None,
            )
            continue

        # Wait for reply only if there's an expectation or it's not the last step
        needs_reply = (expect is not None) or (i < total_steps)
        if not needs_reply:
            # Last step, no expectation: still wait briefly to capture the reply for the log
            needs_reply = True

        reply = await _wait_for_reply(phone, timeout=timeout)

        if reply is None:
            ui.log_error(f"Timeout: no reply within {REPLY_TIMEOUT}s")
            error_log.log_result(
                scenario=scenario["name"], group=group, step=i,
                phone=phone, sent=body, reply=None,
                status="timeout", expect_contains=expect,
                error_detail=f"No reply after {timeout}s",
            )
            failed_steps += 1
            continue

        # Check expectation
        if expect and expect.lower() not in reply.lower():
            detail = f"expected '{expect}' not found in: {reply[:200]}"
            ui.log_error(f"FAIL: {detail}")
            error_log.log_result(
                scenario=scenario["name"], group=group, step=i,
                phone=phone, sent=body, reply=reply,
                status="fail", expect_contains=expect, error_detail=detail,
            )
            failed_steps += 1
        else:
            if expect:
                ui.log_success(f"PASS: reply contains '{expect}'")
            error_log.log_result(
                scenario=scenario["name"], group=group, step=i,
                phone=phone, sent=body, reply=reply,
                status="pass", expect_contains=expect,
            )

    passed = (failed_steps == 0)
    error_log.log_scenario_summary(
        scenario=scenario["name"], group=group,
        passed=passed, total_steps=total_steps, failed_steps=failed_steps,
    )
    return passed


# ── Group runner ───────────────────────────────────────────────────

async def run_group(
    group_name: str,
    scenarios: list[dict[str, Any]],
    phone_names: dict[str, str] | None = None,
    loop_count: int = 0,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Run all scenarios in a group sequentially, weighted-random order.
    loop_count=0 → run through all scenarios once (no repeat).
    loop_count>0 → repeat that many times picking random weighted scenarios.
    Returns a summary dict.
    """
    pool = [s for s in scenarios if s.get("group") == group_name]
    if not pool:
        return {"group": group_name, "total": 0, "passed": 0, "failed": 0}

    total = passed = failed = 0
    sid = session_id or settings.SESSION_ID

    if loop_count == 0:
        # Run each scenario in the group exactly once, in definition order
        for scenario in pool:
            result = await run_scenario(scenario, session_id=sid, phone_names=phone_names)
            total += 1
            if result:
                passed += 1
            else:
                failed += 1
            await asyncio.sleep(1.0)
    else:
        for _ in range(loop_count):
            scenario = pick_scenario(pool, group=group_name)
            result = await run_scenario(scenario, session_id=sid, phone_names=phone_names)
            total += 1
            if result:
                passed += 1
            else:
                failed += 1
            await asyncio.sleep(1.5)

    return {"group": group_name, "total": total, "passed": passed, "failed": failed}


# ── Reply helper ───────────────────────────────────────────────────

async def _drain_replies(phones: set[str]) -> None:
    """Discard any already-queued replies for the given phones (non-blocking)."""
    for phone in phones:
        q = get_reply_queue(phone)
        while True:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break


async def _wait_for_reply(target_phone: str, timeout: float) -> str | None:
    """Wait for a reply on target_phone's dedicated queue, or return None on timeout."""
    q = get_reply_queue(target_phone)
    try:
        body = await asyncio.wait_for(q.get(), timeout=timeout)
        ui.log_reply(target_phone, body)
        return body
    except asyncio.TimeoutError:
        return None

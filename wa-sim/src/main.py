"""
wa-sim entry point.

Usage:
  python -m src.main [options]

Modes
-----
  (default)             Interactive: type messages, see Alfred's replies in real time
  --auto                Run each group sequentially, all scenarios once
  --concurrent          Run all 5 phone groups IN PARALLEL (most realistic stress test)
  --scenario NAME       Run a single named scenario once, then exit
  --group GROUP         Run all scenarios in one group sequentially, then exit

Options
-------
  --loop N              (with --auto / --concurrent) repeat each group N random picks
                        instead of running every scenario once
  --auto-register       Insert a WhatsAppConnection row in the Gateway DB (needs DB_PATH)

Output
------
  output/results.jsonl  every step result (JSON lines)
  output/errors.jsonl   failures only (subset of results.jsonl)
"""

import argparse
import asyncio
import logging
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path

import uvicorn

from . import settings, ui
from .bridge_mock import app as bridge_app, register_session
from .error_log import log_result
from .gateway_client import check_gateway_health, send_message
from .scenarios import (
    load_scenarios,
    pick_scenario,
    run_group,
    run_scenario,
    scenarios_by_group,
    _wait_for_reply,
)
from .virtual_phone import DEFAULT_PHONES, VirtualPhone


# ── Bridge startup ─────────────────────────────────────────────────

def _start_bridge_server() -> None:
    config = uvicorn.Config(
        bridge_app,
        host="0.0.0.0",
        port=settings.BRIDGE_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.0)
    ui.log_info(f"Fake Bridge listening on :{settings.BRIDGE_PORT}")


# ── DB auto-register ───────────────────────────────────────────────

def _auto_register_db() -> None:
    if not settings.DB_PATH:
        ui.log_error("--auto-register requires DB_PATH to be set in .env")
        return
    try:
        db = sqlite3.connect(settings.DB_PATH)
        cur = db.cursor()
        cur.execute(
            "SELECT id FROM whatsappconnection WHERE bridge_session_id = ?",
            (settings.SESSION_ID,),
        )
        if cur.fetchone():
            ui.log_info(f"WhatsAppConnection '{settings.SESSION_ID}' already exists.")
            db.close()
            return
        cur.execute(
            "INSERT INTO whatsappconnection (id, bridge_session_id, label, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (uuid.uuid4().hex, settings.SESSION_ID, "wa-sim"),
        )
        db.commit()
        db.close()
        ui.log_success(f"WhatsAppConnection registered: session_id={settings.SESSION_ID}")
    except Exception as exc:
        ui.log_error(f"auto-register failed: {exc}")


# ── Gateway health check ───────────────────────────────────────────

async def _wait_for_gateway(retries: int = 20, delay: float = 2.0) -> bool:
    for attempt in range(retries):
        if await check_gateway_health():
            return True
        if attempt == 0:
            ui.log_info("Waiting for Gateway to be ready...")
        await asyncio.sleep(delay)
    return False


# ── Run modes ──────────────────────────────────────────────────────

def _phone_names(phones: list[VirtualPhone]) -> dict[str, str]:
    return {p.phone: p.name for p in phones}


async def run_auto_sequential(
    phones: list[VirtualPhone],
    loop_count: int,
) -> None:
    """Run each group one at a time."""
    scenarios = load_scenarios()
    names = _phone_names(phones)
    sid = settings.SESSION_ID
    all_results: list[dict] = []

    for phone in phones:
        group = phone.group
        ui.log_info(f"\n{'─'*60}")
        ui.log_info(f"Group: {group}  ({phone.name} {phone.phone})")
        ui.log_info(f"{'─'*60}")
        summary = await run_group(
            group_name=group,
            scenarios=scenarios,
            phone_names=names,
            loop_count=loop_count,
            session_id=sid,
        )
        all_results.append(summary)
        _print_group_summary(summary)

    _print_final_summary(all_results)


async def run_concurrent(
    phones: list[VirtualPhone],
    loop_count: int,
) -> None:
    """Run all groups concurrently — one asyncio task per group."""
    scenarios = load_scenarios()
    names = _phone_names(phones)
    sid = settings.SESSION_ID

    ui.log_info("Running all groups concurrently...")
    tasks = [
        asyncio.create_task(
            run_group(
                group_name=p.group,
                scenarios=scenarios,
                phone_names=names,
                loop_count=loop_count,
                session_id=sid,
            ),
            name=p.group,
        )
        for p in phones
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results = []
    for phone, result in zip(phones, results):
        if isinstance(result, Exception):
            ui.log_error(f"Group '{phone.group}' crashed: {result}")
            all_results.append({"group": phone.group, "total": 0, "passed": 0, "failed": 1})
        else:
            all_results.append(result)
            _print_group_summary(result)

    _print_final_summary(all_results)


async def run_single_scenario(
    scenario_name: str,
    phones: list[VirtualPhone],
) -> None:
    scenarios = load_scenarios()
    scenario = pick_scenario(scenarios, name=scenario_name)
    names = _phone_names(phones)
    passed = await run_scenario(scenario, phone_names=names)
    status = "PASS" if passed else "FAIL"
    ui.log_info(f"\nResult: {status}")


async def run_single_group(
    group_name: str,
    phones: list[VirtualPhone],
    loop_count: int,
) -> None:
    scenarios = load_scenarios()
    names = _phone_names(phones)
    summary = await run_group(
        group_name=group_name,
        scenarios=scenarios,
        phone_names=names,
        loop_count=loop_count,
    )
    _print_group_summary(summary)


# ── Interactive mode ───────────────────────────────────────────────

async def run_interactive(phones: list[VirtualPhone]) -> None:
    sid = settings.SESSION_ID
    active = phones[0]
    phone_map = {p.phone: p for p in phones}
    names = _phone_names(phones)

    ui.log_info(f"Interactive mode. Active: {active.name} ({active.phone})")
    ui.log_info("Switch phone: '+18005550002: hello'  |  'phones' to list  |  'quit' to exit\n")

    loop = asyncio.get_event_loop()

    while True:
        try:
            raw = await loop.run_in_executor(None, lambda: input("> "))
        except (EOFError, KeyboardInterrupt):
            break

        raw = raw.strip()
        if not raw:
            continue
        if raw.lower() in ("quit", "exit", "q"):
            break
        if raw.lower() == "phones":
            for p in phones:
                ui.log_info(f"  {p.phone}  {p.name}  (group: {p.group})")
            continue

        if raw.startswith("+") and ": " in raw:
            prefix, body = raw.split(": ", 1)
            prefix = prefix.strip()
            if prefix in phone_map:
                active = phone_map[prefix]
                ui.log_info(f"Switched to {active.name} ({active.phone})")
            else:
                ui.log_error(f"Unknown phone: {prefix}")
                continue
        else:
            body = raw

        ui.log_sent(active.phone, body)
        try:
            await send_message(active.phone, active.name, body, session_id=sid)
        except Exception as exc:
            ui.log_error(f"Send failed: {exc}")
            continue

        reply = await _wait_for_reply(active.phone, timeout=30.0)
        if reply is None:
            ui.log_info("(no reply within 30s)")


# ── Summary helpers ────────────────────────────────────────────────

def _print_group_summary(s: dict) -> None:
    rate = f"{s['passed']}/{s['total']}" if s["total"] else "0/0"
    color = "green" if s["failed"] == 0 else "red"
    ui.log_info(
        f"[{color}]  {s['group']:12s}  {rate} passed[/{color}]"
        if s["total"] else f"  {s['group']:12s}  (no scenarios)"
    )


def _print_final_summary(results: list[dict]) -> None:
    total = sum(r["total"] for r in results)
    passed = sum(r["passed"] for r in results)
    failed = sum(r["failed"] for r in results)
    ui.log_info(f"\n{'═'*40}")
    if failed == 0:
        ui.log_success(f"ALL PASS  {passed}/{total} steps")
    else:
        ui.log_error(f"FAILURES  {passed}/{total} passed,  {failed} failed")
    ui.log_info(f"Full log → output/results.jsonl")
    if failed:
        ui.log_info(f"Errors  → output/errors.jsonl")


# ── Main ───────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> None:
    phones = DEFAULT_PHONES
    ui.register_phones(phones)

    _start_bridge_server()
    register_session(settings.SESSION_ID)

    if args.auto_register:
        _auto_register_db()

    if not await _wait_for_gateway():
        ui.log_error(f"Gateway at {settings.GATEWAY_URL} is not reachable. Aborting.")
        sys.exit(1)
    ui.log_success(f"Gateway ready at {settings.GATEWAY_URL}\n")

    if args.scenario:
        await run_single_scenario(args.scenario, phones)
    elif args.group:
        await run_single_group(args.group, phones, loop_count=args.loop)
    elif args.concurrent:
        await run_concurrent(phones, loop_count=args.loop)
    elif args.auto:
        await run_auto_sequential(phones, loop_count=args.loop)
    else:
        await run_interactive(phones)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="wa-sim: multi-user WhatsApp simulator for Alfred"
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--auto", action="store_true",
                      help="Run all groups sequentially, each scenario once")
    mode.add_argument("--concurrent", action="store_true",
                      help="Run all 5 groups in parallel (stress test)")
    mode.add_argument("--scenario", metavar="NAME",
                      help="Run a single named scenario and exit")
    mode.add_argument("--group", metavar="GROUP",
                      help="Run all scenarios in one group (finance/reminders/notes/chat/errors)")

    parser.add_argument("--loop", type=int, default=0, metavar="N",
                        help="With --auto/--concurrent: pick N random scenarios per group "
                             "instead of running each once (0 = run each once)")
    parser.add_argument("--auto-register", action="store_true",
                        help="Insert WhatsAppConnection row in Gateway DB (needs DB_PATH in .env)")

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()

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
  --daemon              Run each phone in its own parallel loop forever; auto-ack reminder pushes
                        Stop with Ctrl-C or:  ./wa-sim/kill.sh

Options
-------
  --loop N              (with --auto / --concurrent) repeat each group N random picks
                        instead of running every scenario once
  --interval N          (with --daemon) seconds between scenario runs (default: 30)
  --stop                Send SIGTERM to a running daemon and exit
  --auto-register       Insert a WhatsAppConnection row in the Gateway DB (needs DB_PATH)

Output
------
  output/results.jsonl  every step result (JSON lines)
  output/errors.jsonl   failures only (subset of results.jsonl)
"""

import argparse
import asyncio
import logging
import os
import random
import signal
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path

import uvicorn

from . import settings, ui
from .bridge_mock import app as bridge_app, register_session, init_reply_queues, get_reply_queue
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

PID_FILE = Path(__file__).parent.parent / "wa-sim.pid"


# ── PID helpers ────────────────────────────────────────────────────

def _write_pid() -> None:
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def _stop_daemon() -> None:
    if not PID_FILE.exists():
        print("No daemon PID file found — is it running?")
        return
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        print("Invalid PID file — removing.")
        _remove_pid()
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (PID {pid})")
    except ProcessLookupError:
        print(f"Daemon (PID {pid}) not found — removing stale PID file.")
        _remove_pid()


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
            "INSERT INTO whatsappconnection (bridge_session_id, label, created_at) "
            "VALUES (?, ?, datetime('now'))",
            (settings.SESSION_ID, "wa-sim"),
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


# ── Daemon mode ────────────────────────────────────────────────────

def _is_reminder_push(body: str) -> bool:
    """True if the message looks like a nudge reminder push (needs an 'ok' ack)."""
    lower = body.lower()
    return "reply" in lower and "confirm" in lower


async def run_daemon(
    phones: list[VirtualPhone],
    interval: float,
    group: str | None,
) -> None:
    """Run one independent scenario loop per phone, all in parallel."""
    from . import gateway_client as _gwc

    scenarios = load_scenarios()
    names = _phone_names(phones)
    sid = settings.SESSION_ID
    active_phones = [p for p in phones if p.group == group] if group else phones

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)

    ui.log_info(
        f"Daemon  {len(active_phones)} phones in parallel  "
        f"interval=~{interval} min (±50%)  group={group or 'all'}"
    )
    ui.log_info("Stop:  Ctrl-C  or  ./wa-sim/kill.sh\n")

    async def _ack_pushes(phone: VirtualPhone) -> None:
        q = get_reply_queue(phone.phone)
        while True:
            try:
                body = q.get_nowait()
                if _is_reminder_push(body):
                    ui.log_reply(phone.phone, body)
                    ui.log_sent(phone.phone, "ok  [auto-ack]")
                    try:
                        await _gwc.send_message(phone.phone, phone.name, "ok", session_id=sid)
                    except Exception as exc:
                        ui.log_error(f"Auto-ack failed: {exc}")
            except asyncio.QueueEmpty:
                break

    async def _wait_interval(phone: VirtualPhone) -> None:
        lo = max(interval * 0.5, 0.5)
        wait_min = random.uniform(lo, interval * 1.5)
        ui.log_info(f"[{phone.name}] Next in {wait_min:.1f} min …")
        deadline = loop.time() + wait_min * 60
        while not stop_event.is_set():
            await _ack_pushes(phone)
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=min(2.0, remaining))
            except asyncio.TimeoutError:
                pass

    async def phone_loop(phone: VirtualPhone) -> None:
        phone_scenarios = [s for s in scenarios if s.get("group") == phone.group]
        total = passed = failed = 0
        while not stop_event.is_set():
            scenario = pick_scenario(phone_scenarios)
            ui.log_info(f"\n── [{phone.name}] {scenario['name']} ──")
            result = await run_scenario(scenario, session_id=sid, phone_names=names)
            total += 1
            if result:
                passed += 1
                ui.log_success(f"[{phone.name}] PASS  {passed}/{total}")
            else:
                failed += 1
                ui.log_error(f"[{phone.name}] FAIL  {passed}/{total}  ({failed} failures)")
            if not stop_event.is_set():
                await _wait_interval(phone)

    tasks = [asyncio.create_task(phone_loop(p), name=p.name) for p in active_phones]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        loop.remove_signal_handler(signal.SIGTERM)
        _remove_pid()
        ui.log_info("\nDaemon stopped.")


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

    init_reply_queues([p.phone for p in phones])
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
    elif args.daemon:
        _write_pid()
        await run_daemon(phones, interval=args.interval, group=args.group)
    elif args.concurrent:
        await run_concurrent(phones, loop_count=args.loop)
    elif args.auto:
        await run_auto_sequential(phones, loop_count=args.loop)
    elif args.group:
        await run_single_group(args.group, phones, loop_count=args.loop)
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
    mode.add_argument("--daemon", action="store_true",
                      help="Run random scenarios forever; auto-ack reminder pushes between runs")

    parser.add_argument("--group", metavar="GROUP",
                        help="With --daemon: filter to this group. "
                             "Standalone: run all scenarios in the group once and exit. "
                             "(finance / reminders / notes / chat / errors)")
    parser.add_argument("--loop", type=int, default=0, metavar="N",
                        help="With --auto/--concurrent: pick N random scenarios per group "
                             "instead of running each once (0 = run each once)")
    parser.add_argument("--interval", type=float, default=5.0, metavar="N",
                        help="With --daemon: average minutes between scenario runs (default: 5, "
                             "actual wait is random ±50%%)")
    parser.add_argument("--stop", action="store_true",
                        help="Stop a running daemon and exit")
    parser.add_argument("--auto-register", action="store_true",
                        help="Insert WhatsAppConnection row in Gateway DB (needs DB_PATH in .env)")

    args = parser.parse_args()

    if args.stop:
        _stop_daemon()
        return

    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()

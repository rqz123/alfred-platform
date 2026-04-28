"""
Error and result logging for wa-sim.

Each scenario run appends a JSON line to output/results.jsonl.
Failures also append to output/errors.jsonl (a subset for quick scanning).

Log entry shape:
{
  "ts": "2025-04-27T10:30:00.123456",
  "scenario": "add_expense_single",
  "group": "finance",
  "step": 1,
  "phone": "+18005550001",
  "sent": "花了$40吃午饭",
  "reply": "Expense recorded: $40.00 (food)",
  "status": "pass" | "fail" | "timeout" | "send_error",
  "expect_contains": "$40",       # null if no expectation
  "error_detail": ""              # populated on failure
}
"""

import json
from datetime import datetime, timezone
from pathlib import Path

_output_dir = Path(__file__).parent.parent / "output"
_results_path = _output_dir / "results.jsonl"
_errors_path = _output_dir / "errors.jsonl"


def _ensure_output_dir() -> None:
    _output_dir.mkdir(parents=True, exist_ok=True)


def log_result(
    scenario: str,
    group: str,
    step: int,
    phone: str,
    sent: str,
    reply: str | None,
    status: str,
    expect_contains: str | None = None,
    error_detail: str = "",
) -> None:
    """Append a result entry to results.jsonl (and errors.jsonl on failure)."""
    _ensure_output_dir()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "group": group,
        "step": step,
        "phone": phone,
        "sent": sent,
        "reply": reply,
        "status": status,
        "expect_contains": expect_contains,
        "error_detail": error_detail,
    }
    line = json.dumps(entry, ensure_ascii=False)
    with open(_results_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if status != "pass":
        with open(_errors_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def log_scenario_summary(
    scenario: str,
    group: str,
    passed: bool,
    total_steps: int,
    failed_steps: int,
) -> None:
    """Append a summary line at the end of a scenario run."""
    _ensure_output_dir()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "summary",
        "scenario": scenario,
        "group": group,
        "passed": passed,
        "total_steps": total_steps,
        "failed_steps": failed_steps,
    }
    line = json.dumps(entry, ensure_ascii=False)
    with open(_results_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

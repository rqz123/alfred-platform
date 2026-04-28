"""
Terminal UI for wa-sim using Rich.

Output format (one line per event):
  10:30:01  Dave          →  Hello Alfred
  10:30:08  Alfred → Dave ←  Hello! How can I assist you today?
  10:30:08  [add_expense_single 1/3]
"""

from datetime import datetime

from rich.console import Console
from rich.text import Text

from .virtual_phone import VirtualPhone

_console = Console(highlight=False)

# Map phone → VirtualPhone for name/color lookup
_phone_map: dict[str, VirtualPhone] = {}


def register_phones(phones: list[VirtualPhone]) -> None:
    for p in phones:
        _phone_map[p.phone] = p


def _name_and_color(phone: str) -> tuple[str, str]:
    vp = _phone_map.get(phone)
    if vp:
        return vp.name, vp.color
    return phone, "white"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log_sent(phone: str, body: str) -> None:
    name, color = _name_and_color(phone)
    line = Text()
    line.append(f"{_ts()}  ", style="dim")
    line.append(f"{name:<12}", style=f"bold {color}")
    line.append("  →  ", style="dim")
    line.append(body)
    _console.print(line)


def log_reply(recipient_phone: str, body: str) -> None:
    name, color = _name_and_color(recipient_phone)
    line = Text()
    line.append(f"{_ts()}  ", style="dim")
    line.append("Alfred", style="bold white")
    line.append(" → ", style="dim")
    line.append(f"{name:<8}", style=f"bold {color}")
    line.append("  ←  ", style="dim")
    line.append(body, style="italic")
    _console.print(line)


def log_scenario(name: str, step: int, total: int) -> None:
    line = Text()
    line.append(f"{_ts()}  ", style="dim")
    line.append(f"[{name}  {step}/{total}]", style="dim cyan")
    _console.print(line)


def log_info(msg: str) -> None:
    _console.print(f"[dim]{msg}[/dim]")


def log_success(msg: str) -> None:
    _console.print(f"[bold green]{msg}[/bold green]")


def log_error(msg: str) -> None:
    _console.print(f"[bold red]{msg}[/bold red]")

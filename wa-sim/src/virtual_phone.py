from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class VirtualPhone:
    phone: str    # e.g. "+18005550001"
    name: str     # display name, e.g. "Alice"
    color: str    # rich markup color
    group: str    # scenario group this phone is assigned to


@dataclass
class SimMessage:
    phone: str
    direction: Literal["out", "in"]   # out = user→Alfred, in = Alfred→user
    body: str
    ts: datetime = field(default_factory=datetime.now)


# Five virtual phones — each owns a scenario group.
# Group names match the `group` field in scenarios.yaml.
DEFAULT_PHONES = [
    VirtualPhone(phone="+18005550001", name="Alice",  color="cyan",    group="finance"),
    VirtualPhone(phone="+18005550002", name="Bob",    color="green",   group="reminders"),
    VirtualPhone(phone="+18005550003", name="Carol",  color="yellow",  group="notes"),
    VirtualPhone(phone="+18005550004", name="Dave",   color="magenta", group="chat"),
    VirtualPhone(phone="+18005550005", name="Eve",    color="red",     group="errors"),
]

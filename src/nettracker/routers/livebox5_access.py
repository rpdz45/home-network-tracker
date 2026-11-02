"""Strict schedule parsing and command preparation; no network I/O."""

import re
from dataclasses import dataclass

from nettracker.routers.control import AccessControlError


@dataclass(frozen=True)
class ScheduleState:
    override: str
    value: str

    @property
    def blocked(self) -> bool:
        return self.value == "Disable"


def parse_schedule(reply: object) -> ScheduleState:
    """Reject missing, refused or ambiguous replies instead of guessing access."""
    if not isinstance(reply, dict):
        raise AccessControlError("invalid Livebox schedule response")
    if "error" in reply or reply.get("errors") or reply.get("status") is not True:
        raise AccessControlError("Livebox schedule is unavailable")
    data = reply.get("data")
    info = data.get("scheduleInfo") if isinstance(data, dict) else None
    if not isinstance(info, dict) or info.get("enable") is not True:
        raise AccessControlError("an enabled existing schedule is required")
    override = info.get("override")
    value = info.get("value")
    if (
        not isinstance(override, str)
        or override not in {"", "Enable", "Disable"}
        or not isinstance(value, str)
        or value not in {"Enable", "Disable"}
        or (override and override != value)
    ):
        raise AccessControlError("Livebox schedule state is ambiguous")
    return ScheduleState(override, value)


def override_parameters(
    mac: str,
    state: ScheduleState,
    *,
    blocked: bool,
    protected_macs: frozenset[str],
    confirmed: bool = False,
) -> dict[str, object]:
    """Prepare Scheduler.overrideSchedule; release restores the existing schedule."""
    if confirmed is not True or type(blocked) is not bool:
        raise AccessControlError("an explicit confirmed action is required")
    if re.fullmatch(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", mac) is None:
        raise AccessControlError("invalid target MAC")
    octets = bytes.fromhex(mac.replace(":", ""))
    normalized = mac.upper()
    if not any(octets) or octets[0] & 1:
        raise AccessControlError("a nonzero unicast MAC is required")
    if normalized in {value.upper() for value in protected_macs}:
        raise AccessControlError("the target is protected")
    if not isinstance(state, ScheduleState):
        raise AccessControlError("a validated schedule is required")
    if not blocked and state.override != "Disable":
        raise AccessControlError("no forced block can be released")
    return {"type": "ToD", "ID": normalized, "override": "Disable" if blocked else ""}

"""Bounded ICMP probes; all subprocess access is replaceable in offline tests."""

import math
import os
import platform
import re
import shutil
import subprocess  # nosec B404
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

from nettracker.discovery.scope import ScopeError, require_allowed_target
from nettracker.errors import NetTrackerError

_WINDOWS_TIMEOUT = re.compile(
    r"request timed out|d[ée]lai d.attente.*d[ée]pass[ée]|zeit[üu]berschreitung|"
    r"tiempo de espera.*agotado|esgotado.*tempo|tempo.*esgotado",
    re.IGNORECASE,
)

Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]
_RTT = re.compile(
    r"(?:time|temps|zeit|tiempo|tempo)\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE
)


class PingError(NetTrackerError):
    """The probe could not run reliably; do not interpret this as an offline host."""


@dataclass(frozen=True)
class PingResult:
    sent: int
    received: int
    latency_ms: float | None

    def __post_init__(self) -> None:
        if not 1 <= self.sent <= 5 or not 0 <= self.received <= self.sent:
            raise ValueError("invalid ping packet counts")
        if self.received == 0:
            if self.latency_ms is not None:
                raise ValueError("no reply must have no latency")
        elif self.latency_ms is None or not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("a reply requires a finite non-negative latency")

    @property
    def online(self) -> bool:
        return self.received > 0

    @property
    def packet_loss_pct(self) -> float:
        return 100.0 * (self.sent - self.received) / self.sent


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        argv,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )


def probe_ping(
    target: str,
    allowed_subnets: list[IPv4Network],
    *,
    enabled: bool = False,
    packets: int = 3,
    timeout: float = 1.0,
    runner: Runner | None = None,
    system: str | None = None,
) -> PingResult:
    """Probe one scoped literal IPv4, never a network, hostname or shell fragment.

    A process failure/timeout is an error, not evidence that a device is offline.
    Linux exit 1 means no echo reply. Windows exit 1 is accepted only with a
    recognized timeout message;
    other diagnostics fail closed. Successful but unrecognized output fails closed.
    """
    if not enabled:
        raise PingError("ICMP monitoring requires explicit activation")
    parsed = require_allowed_target(target, allowed_subnets)
    if not isinstance(parsed, IPv4Address):
        raise ScopeError("ping requires a single IPv4 host, not a subnet")
    if not isinstance(packets, int) or isinstance(packets, bool) or not 1 <= packets <= 5:
        raise ValueError("ping packets must be between 1 and 5")
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 5:
        raise ValueError("ping timeout must be finite and between 0.1 and 5 seconds")
    # Refuse network/broadcast addresses in the configured subnet before process creation.
    if any(
        parsed in net and parsed in (net.network_address, net.broadcast_address)
        for net in allowed_subnets
        if net.prefixlen < 31
    ):
        raise ScopeError("ping refuses configured network/broadcast addresses")
    host_os = system if system is not None else platform.system()
    if host_os not in ("Linux", "Windows"):
        raise PingError("ping monitoring currently supports Linux and Windows only")
    executable = shutil.which("ping") if runner is None else "ping"
    if executable is None:
        raise PingError("ping executable not found; install the OS ping utility")
    transport = runner if runner is not None else _run
    if host_os == "Windows":
        options = ["-4", "-n", "1", "-w", str(math.ceil(timeout * 1000)), "-l", "16"]
    else:
        options = ["-4", "-n", "-c", "1", "-W", str(timeout), "-s", "16"]
    latencies: list[float] = []
    for _ in range(packets):
        try:
            reply = transport([executable, *options, str(parsed)], timeout + 0.5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise PingError("ping process failed, timed out or lacks permission") from exc
        if reply.stderr.strip() or reply.returncode not in (0, 1):
            raise PingError("ping reported a local execution or permission error")
        if reply.returncode == 1:
            if host_os == "Windows" and not _WINDOWS_TIMEOUT.search(reply.stdout):
                raise PingError("unsupported Windows failure; no offline measurement saved")
            continue
        matches = _RTT.findall(reply.stdout)
        if len(matches) != 1:
            raise PingError("ping reply format is unsupported; no measurement saved")
        latency = float(matches[0].replace(",", "."))
        if not math.isfinite(latency) or latency > (timeout + 0.5) * 1000:
            raise PingError("ping reported an invalid round-trip time")
        latencies.append(latency)
    return PingResult(
        packets, len(latencies), sum(latencies) / len(latencies) if latencies else None
    )

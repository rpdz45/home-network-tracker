"""Offline tests for the passive neighbor cache reader."""

from ipaddress import IPv4Network

import pytest

from nettracker.discovery.passive import (
    Neighbor,
    NeighborReadError,
    parse_neighbors,
    read_neighbors,
    run_command,
)
from nettracker.discovery.scope import ScopeError

ALLOWED = [IPv4Network("192.168.1.0/24")]


def test_linux_filters_missing_mac_failed_and_outside_scope() -> None:
    text = (
        "192.168.1.2 dev eth0 lladdr 02:11:22:33:44:55 REACHABLE\n"
        "192.168.1.2 dev eth0 lladdr 02:11:22:33:44:55 STALE\n"
        "192.168.1.3 dev eth0 INCOMPLETE\n"
        "192.168.1.4 dev eth0 lladdr 00:00:00:00:00:00 FAILED\n"
        "192.168.2.2 dev eth0 lladdr 02:11:22:33:44:66 STALE\n"
        "8.8.8.8 dev eth0 lladdr 02:11:22:33:44:77 STALE\n"
    )
    assert parse_neighbors(text, ALLOWED) == [Neighbor("192.168.1.2", "02:11:22:33:44:55")]


def test_windows_arp_table_formats_and_filters_multicast() -> None:
    text = (
        "Interface: 192.168.1.100 --- 0x6\n"
        "  Internet Address      Physical Address      Type\n"
        "  192.168.1.1           02-11-22-33-44-55     dynamic\n"
        "  192.168.1.1           02-11-22-33-44-55     dynamic\n"
        "  192.168.1.255         ff-ff-ff-ff-ff-ff     static\n"
        "  999.168.1.2           02-11-22-33-44-77     dynamic\n"
    )
    assert parse_neighbors(text, ALLOWED) == [Neighbor("192.168.1.1", "02:11:22:33:44:55")]


def test_runner_is_injected_and_never_called_on_empty_scope() -> None:
    calls: list[tuple[list[str], float]] = []

    def runner(argv: list[str], timeout: float) -> str:
        calls.append((argv, timeout))
        return "192.168.1.2 dev eth0 lladdr 02:11:22:33:44:55 STALE"

    with pytest.raises(ScopeError):
        read_neighbors([], runner=runner)
    assert calls == []
    assert read_neighbors(ALLOWED, runner=runner, platform="linux", timeout=2) == [
        Neighbor("192.168.1.2", "02:11:22:33:44:55")
    ]
    assert calls == [(["ip", "-4", "neigh", "show"], 2)]
    read_neighbors(ALLOWED, runner=runner, platform="win32")
    assert calls[-1][0] == ["arp", "-a"]


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="timeout"):
        read_neighbors(ALLOWED, timeout=0)


def test_command_rejects_arbitrary_arguments_before_subprocess() -> None:
    with pytest.raises(NeighborReadError, match="not allowed"):
        run_command(["ip", "-4", "neigh", "show", "8.8.8.8"], 5)


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError])
def test_os_failure_is_reported_without_real_subprocess(
    monkeypatch: pytest.MonkeyPatch, failure: type[OSError]
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise failure("simulated OS failure")

    monkeypatch.setattr("nettracker.discovery.passive.subprocess.run", fail)
    with pytest.raises(NeighborReadError, match="cannot read local neighbor cache"):
        run_command(["ip", "-4", "neigh", "show"], 1)

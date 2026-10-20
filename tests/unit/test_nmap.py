"""Nmap tests use invented XML and replace every process invocation."""

import subprocess
from ipaddress import IPv4Network
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nettracker.config import ScanSettings
from nettracker.discovery.nmap import (
    MAX_XML_CHARACTERS,
    NmapDiscoveryError,
    discover_nmap,
    parse_nmap_xml,
    run_nmap,
)
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError

ALLOWED = [IPv4Network("192.168.1.0/24")]
TARGET = "192.168.1.0/24"
HOST = (
    '<host><status state="up"/><address addr="192.168.1.2" addrtype="ipv4"/>'
    '<address addr="02:11:22:33:44:55" addrtype="mac"/></host>'
)


def xml(hosts: str = HOST) -> str:
    return (
        '<!DOCTYPE nmaprun><nmaprun scanner="nmap">'
        + hosts
        + '<runstats><finished exit="success"/></runstats></nmaprun>'
    )


def fail_runner(*_args: object) -> str:
    pytest.fail("subprocess must not be called")


def test_opt_in_before_any_runner() -> None:
    with pytest.raises(NmapDiscoveryError, match="explicitly enabled"):
        discover_nmap(TARGET, ALLOWED, runner=fail_runner)


@pytest.mark.parametrize(
    "target",
    ["8.8.8.8", "192.168.2.0/24", "router.local", "::1", "--script=all", "192.168.1.2;id"],
)
def test_bad_targets_never_call_runner(target: str) -> None:
    with pytest.raises(ScopeError):
        discover_nmap(target, ALLOWED, enabled=True, runner=fail_runner)


def test_large_target_never_calls_runner() -> None:
    with pytest.raises(ScopeError, match="256-address"):
        discover_nmap(
            "192.168.0.0/16",
            [IPv4Network("192.168.0.0/16")],
            enabled=True,
            runner=fail_runner,
        )


@pytest.mark.parametrize("timeout", [0, -1, 0.5, 121, float("inf"), float("nan")])
def test_bad_timeouts_never_call_runner(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        discover_nmap(TARGET, ALLOWED, enabled=True, runner=fail_runner, timeout=timeout)
    with pytest.raises(ValidationError):
        ScanSettings(nmap_timeout_seconds=timeout)


def test_valid_target_deduplicates_and_passes_timeout() -> None:
    calls: list[tuple[str, float]] = []

    def runner(target: str, timeout: float) -> str:
        calls.append((target, timeout))
        return xml(HOST + HOST.replace("02:11:22:33:44:55", "02-11-22-33-44-55"))

    assert discover_nmap(TARGET, ALLOWED, enabled=True, runner=runner, timeout=12) == [
        Neighbor("192.168.1.2", "02:11:22:33:44:55")
    ]
    assert calls == [(TARGET, 12)]


@pytest.mark.parametrize("target", [TARGET, "192.168.1.2"])
def test_valid_host_or_network_target(target: str) -> None:
    assert len(parse_nmap_xml(xml(), target, ALLOWED)) == 1


@pytest.mark.parametrize("ip", ["192.168.2.2", "8.8.8.8", "::1", "192.168.1.0/24"])
def test_out_of_scope_or_non_host_responses_fail_closed(ip: str) -> None:
    with pytest.raises(ScopeError):
        parse_nmap_xml(xml(HOST.replace("192.168.1.2", ip)), TARGET, ALLOWED)


@pytest.mark.parametrize("target", ["192.168.1.3", "192.168.1.128/25"])
def test_responses_must_be_within_requested_target(target: str) -> None:
    with pytest.raises(ScopeError, match="outside requested"):
        parse_nmap_xml(xml(), target, ALLOWED)


@pytest.mark.parametrize(
    "document",
    [
        "<nmaprun>",
        "<other/>",
        '<nmaprun><runstats><finished exit="error"/></runstats></nmaprun>',
        "x" * (MAX_XML_CHARACTERS + 1),
        '<!DOCTYPE nmaprun [<!ENTITY x "secret">]><nmaprun>&x;</nmaprun>',
        '<!DOCTYPE nmaprun [<!ENTITY x SYSTEM "file:///nonexistent">]><nmaprun>&x;</nmaprun>',
    ],
)
def test_invalid_or_unsafe_xml(document: str) -> None:
    with pytest.raises(NmapDiscoveryError):
        parse_nmap_xml(document, TARGET, ALLOWED)


@pytest.mark.parametrize("mac", ["", "invalid", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"])
def test_no_usable_mac_is_not_silent_success(mac: str) -> None:
    with pytest.raises(NmapDiscoveryError, match="no usable MAC"):
        parse_nmap_xml(xml(HOST.replace("02:11:22:33:44:55", mac)), TARGET, ALLOWED)


def test_missing_mac_and_partial_result_are_visible(caplog: pytest.LogCaptureFixture) -> None:
    without_mac = HOST.replace('<address addr="02:11:22:33:44:55" addrtype="mac"/>', "")
    with pytest.raises(NmapDiscoveryError, match="no usable MAC"):
        parse_nmap_xml(xml(without_mac), TARGET, ALLOWED)
    assert len(parse_nmap_xml(xml(HOST + without_mac), TARGET, ALLOWED)) == 1
    assert "omitted 1 online host" in caplog.text


def test_empty_down_and_ipv6_only_hosts_are_not_devices() -> None:
    assert parse_nmap_xml(xml(""), TARGET, ALLOWED) == []
    assert parse_nmap_xml(xml(HOST.replace('state="up"', 'state="down"')), TARGET, ALLOWED) == []
    assert (
        parse_nmap_xml(xml(HOST.replace('addrtype="ipv4"', 'addrtype="ipv6"')), TARGET, ALLOWED)
        == []
    )
    assert parse_nmap_xml(xml(HOST.replace('<status state="up"/>', "")), TARGET, ALLOWED) == []


def test_fixed_command_without_shell_and_with_timeout() -> None:
    with patch("nettracker.discovery.nmap.subprocess.run") as run:
        run.return_value.stdout = xml()
        assert run_nmap(TARGET, 15) == xml()
        args, kwargs = run.call_args
        assert args[0] == [
            "nmap",
            "-sn",
            "-n",
            "--max-rate",
            "10",
            "--max-retries",
            "1",
            "--host-timeout",
            "5s",
            "-oX",
            "-",
            TARGET,
        ]
        assert kwargs == {
            "check": True,
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "timeout": 15,
        }


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(),
        PermissionError(),
        subprocess.TimeoutExpired("nmap", 1),
        subprocess.CalledProcessError(1, "nmap"),
        UnicodeError(),
    ],
)
def test_process_errors_are_explicit(error: Exception) -> None:
    with (
        patch("nettracker.discovery.nmap.subprocess.run", side_effect=error),
        pytest.raises(NmapDiscoveryError, match="unavailable"),
    ):
        run_nmap(TARGET, 10)


def test_direct_runner_rejects_injection_without_process() -> None:
    with patch("nettracker.discovery.nmap.subprocess.run") as run:
        with pytest.raises(ScopeError):
            run_nmap("--script=all", 10)
        run.assert_not_called()


def test_default_timeout_and_config_are_conservative() -> None:
    assert not ScanSettings().nmap_fallback
    assert ScanSettings().nmap_timeout_seconds == 30
    seen: dict[str, Any] = {}

    def runner(target: str, timeout: float) -> str:
        seen["timeout"] = timeout
        return xml("")

    discover_nmap(TARGET, ALLOWED, enabled=True, runner=runner)
    assert seen == {"timeout": 30.0}

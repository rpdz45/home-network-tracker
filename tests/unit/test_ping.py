"""No test launches ping; fixture output and subprocesses are invented."""

import subprocess
from ipaddress import IPv4Network
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from nettracker.config import MonitorSettings
from nettracker.discovery.scope import ScopeError
from nettracker.monitor.ping import PingError, PingResult, _run, probe_ping

ALLOWED = [IPv4Network("192.168.1.0/24")]
IP = "192.168.1.2"


def completed(
    text: str = "64 bytes from 192.168.1.2: time=1.5 ms", code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["ping"], code, text, stderr)


def test_disabled_never_calls_process() -> None:
    runner = Mock(side_effect=AssertionError("no real process"))
    with pytest.raises(PingError, match="activation"):
        probe_ping(IP, ALLOWED, runner=runner)
    runner.assert_not_called()


@pytest.mark.parametrize(
    "target",
    [
        "8.8.8.8",
        "192.168.2.2",
        "::1",
        "fixture.local",
        "192.168.1.0/24",
        "192.168.1.0",
        "192.168.1.255",
        "192.168.1.2;echo x",
    ],
)
def test_scope_before_runner(target: str) -> None:
    runner = Mock(side_effect=AssertionError("no real process"))
    with pytest.raises(ScopeError):
        probe_ping(target, ALLOWED, enabled=True, runner=runner)
    runner.assert_not_called()


@pytest.mark.parametrize("scope", [[], [IPv4Network("8.8.8.0/24")]])
def test_bad_scope(scope: list[IPv4Network]) -> None:
    runner = Mock()
    with pytest.raises(ScopeError):
        probe_ping(IP, scope, enabled=True, runner=runner)
    runner.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, 0.09, 5.01, float("inf"), float("nan")])
def test_invalid_timeouts(timeout: float) -> None:
    runner = Mock()
    with pytest.raises(ValueError, match="timeout"):
        probe_ping(IP, ALLOWED, enabled=True, timeout=timeout, runner=runner)
    with pytest.raises(ValidationError):
        MonitorSettings(timeout_seconds=timeout)
    runner.assert_not_called()


@pytest.mark.parametrize("packets", [0, -1, 6, True])
def test_invalid_packet_count(packets: int) -> None:
    runner = Mock()
    with pytest.raises(ValueError, match="packets"):
        probe_ping(IP, ALLOWED, enabled=True, packets=packets, runner=runner)
    runner.assert_not_called()


@pytest.mark.parametrize("os_name", ["Linux", "Windows"])
def test_mixed_replies_and_command(os_name: str) -> None:
    runner = Mock(
        side_effect=[completed(), completed("Request timed out.", code=1), completed("temps<1 ms")]
    )
    result = probe_ping(IP, ALLOWED, enabled=True, runner=runner, system=os_name, timeout=0.5)
    assert result.online
    assert result.received == 2
    assert result.packet_loss_pct == pytest.approx(100 / 3)
    assert result.latency_ms == 1.25
    for call in runner.call_args_list:
        argv, bound = call.args
        assert argv[0] == "ping" and argv[-1] == IP
        assert "-4" in argv and bound == 1.0
        assert ("-w" if os_name == "Windows" else "-W") in argv
        assert ("-n" if os_name == "Windows" else "-c") in argv


@pytest.mark.parametrize(
    "text", ["time=2.1 ms", "temps=2,1 ms", "Zeit=2.1ms", "tiempo=2,1 ms", "tempo=2.1 ms"]
)
def test_localized_rtt(text: str) -> None:
    runner = Mock(return_value=completed(text))
    result = probe_ping(IP, ALLOWED, enabled=True, packets=1, runner=runner, system="Windows")
    assert result.latency_ms == 2.1


def test_all_missing_is_not_a_transport_error() -> None:
    result = probe_ping(
        IP, ALLOWED, enabled=True, runner=Mock(return_value=completed(code=1)), system="Linux"
    )
    assert result == PingResult(3, 0, None)
    assert not result.online and result.packet_loss_pct == 100


@pytest.mark.parametrize(
    "reply",
    [
        completed("unsupported output"),
        completed("time=99999 ms"),
        completed("time=1 ms time=2 ms"),
        completed(code=2),
        completed(code=1, stderr="permission denied"),
    ],
)
def test_unreliable_measurements_raise(reply: subprocess.CompletedProcess[str]) -> None:
    with pytest.raises(PingError):
        probe_ping(IP, ALLOWED, enabled=True, runner=Mock(return_value=reply), system="Linux")


@pytest.mark.parametrize(
    "failure", [PermissionError(), FileNotFoundError(), subprocess.TimeoutExpired("ping", 1)]
)
def test_process_failures_are_not_offline(failure: Exception) -> None:
    with pytest.raises(PingError):
        probe_ping(IP, ALLOWED, enabled=True, runner=Mock(side_effect=failure), system="Linux")


def test_keyboard_interrupt_propagates() -> None:
    with pytest.raises(KeyboardInterrupt):
        probe_ping(
            IP, ALLOWED, enabled=True, runner=Mock(side_effect=KeyboardInterrupt), system="Linux"
        )


def test_unsupported_os_and_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(PingError, match="supports"):
        probe_ping(IP, ALLOWED, enabled=True, runner=Mock(), system="Darwin")
    monkeypatch.setattr("nettracker.monitor.ping.shutil.which", lambda _: None)
    with pytest.raises(PingError, match="not found"):
        probe_ping(IP, ALLOWED, enabled=True, system="Linux")


def test_real_adapter_is_mocked_at_subprocess_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock(return_value=completed())
    monkeypatch.setattr("nettracker.monitor.ping.subprocess.run", process)
    monkeypatch.setattr("nettracker.monitor.ping.shutil.which", lambda _: "/fixture/bin/ping")
    monkeypatch.setattr("nettracker.monitor.ping.platform.system", lambda: "Linux")
    result = probe_ping(IP, ALLOWED, enabled=True, packets=1)
    assert result.received == 1
    argv = process.call_args.args[0]
    assert argv[0] == "/fixture/bin/ping"
    kwargs = process.call_args.kwargs
    assert kwargs["timeout"] == 1.5
    assert kwargs["env"]["LC_ALL"] == "C"
    assert "shell" not in kwargs
    assert _run(["fixture"], 0.5).returncode == 0


@pytest.mark.parametrize(
    ("sent", "received", "latency"),
    [
        (0, 0, None),
        (6, 1, 1.0),
        (1, 2, 1.0),
        (1, 0, 1.0),
        (1, 1, None),
        (1, 1, -1.0),
        (1, 1, float("nan")),
    ],
)
def test_invalid_result(sent: int, received: int, latency: float | None) -> None:
    with pytest.raises(ValueError):
        PingResult(sent, received, latency)


def test_windows_permission_stdout_is_not_offline() -> None:
    runner = Mock(return_value=completed("PING: transmit failed. General failure.", code=1))
    with pytest.raises(PingError, match="Windows failure"):
        probe_ping(IP, ALLOWED, enabled=True, runner=runner, system="Windows")

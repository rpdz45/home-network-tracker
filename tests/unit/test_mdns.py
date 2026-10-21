"""mDNS transport is replaced; DNS messages contain invented fixture names only."""

from ipaddress import IPv4Network
from unittest.mock import Mock

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.rcode
import dns.rrset
import pytest
from pydantic import ValidationError

from nettracker.config import ScanSettings
from nettracker.discovery.mdns import _local_hostname, mdns_hostname
from nettracker.discovery.scope import ScopeError

ALLOWED = [IPv4Network("192.168.1.0/24")]
IP = "192.168.1.2"
OWNER = "2.1.168.192.in-addr.arpa."


def test_disabled_does_not_open_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = Mock(side_effect=AssertionError("network forbidden"))
    monkeypatch.setattr("nettracker.discovery.mdns.dns.query.udp", transport)
    assert mdns_hostname(IP, ALLOWED) is None
    transport.assert_not_called()


@pytest.mark.parametrize("target", ["8.8.8.8", "192.168.2.2", "::1", "x.local", "192.168.1.0/24"])
def test_scope_is_checked_before_transport(target: str) -> None:
    transport = Mock(side_effect=AssertionError("network forbidden"))
    with pytest.raises(ScopeError):
        mdns_hostname(target, ALLOWED, enabled=True, lookup=transport)
    transport.assert_not_called()


@pytest.mark.parametrize("scope", [[], [IPv4Network("8.8.8.0/24")]])
def test_invalid_scope_never_opens_transport(scope: list[IPv4Network]) -> None:
    transport = Mock(side_effect=AssertionError("network forbidden"))
    with pytest.raises(ScopeError):
        mdns_hostname(IP, scope, enabled=True, lookup=transport)
    transport.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, 0.09, 5.1, float("inf"), float("nan")])
def test_timeout_is_bounded_in_api_and_config(timeout: float) -> None:
    transport = Mock(side_effect=AssertionError("network forbidden"))
    with pytest.raises(ValueError, match="timeout"):
        mdns_hostname(IP, ALLOWED, enabled=True, timeout=timeout, lookup=transport)
    with pytest.raises(ValidationError):
        ScanSettings(mdns_timeout_seconds=timeout)
    transport.assert_not_called()


def test_config_default_and_injected_transport() -> None:
    assert not ScanSettings().mdns_enabled
    assert ScanSettings().mdns_timeout_seconds == 1.0
    transport = Mock(return_value="fixture.local")
    assert (
        mdns_hostname(IP, ALLOWED, enabled=True, timeout=0.5, lookup=transport) == "fixture.local"
    )
    transport.assert_called_once_with(IP, 0.5)


@pytest.mark.parametrize("failure", [TimeoutError(), PermissionError()])
def test_transport_failure_is_non_fatal(failure: Exception) -> None:
    transport = Mock(side_effect=failure)
    assert mdns_hostname(IP, ALLOWED, enabled=True, lookup=transport) is None


def test_interrupt_propagates() -> None:
    with pytest.raises(KeyboardInterrupt):
        mdns_hostname(IP, ALLOWED, enabled=True, lookup=Mock(side_effect=KeyboardInterrupt))


@pytest.mark.parametrize("name", ["fixture.local.", "FiXtUrE.LoCaL.", "one.two.local."])
def test_local_name_normalization(name: str) -> None:
    assert _local_hostname(dns.name.from_text(name)) == name.rstrip(".").lower()


@pytest.mark.parametrize(
    "name", ["local.", "external.example.", "_service.local.", "-bad.local.", r"bad\010.local."]
)
def test_invalid_names_are_rejected(name: str) -> None:
    assert _local_hostname(dns.name.from_text(name)) is None


def test_overlong_name_is_rejected() -> None:
    with pytest.raises(dns.name.NameTooLong):
        dns.name.Name((b"a" * 63,) * 4 + (b"local", b""))


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("valid", "fixture.local"),
        ("empty", None),
        ("wrong_owner", None),
        ("wrong_type", None),
        ("wrong_class", None),
        ("expired", None),
        ("external", None),
        ("ambiguous", None),
        ("duplicate", "fixture.local"),
        ("error", None),
        ("truncated", None),
        ("wrong_id", None),
        ("non_response", None),
    ],
)
def test_udp_protocol_validation(
    monkeypatch: pytest.MonkeyPatch, scenario: str, expected: str | None
) -> None:
    def answer(query: dns.message.Message, where: str, **kwargs: object) -> dns.message.Message:
        assert where == IP
        assert kwargs == {
            "port": 5353,
            "timeout": 0.5,
            "ignore_unexpected": True,
            "ignore_errors": True,
        }
        assert query.flags == 0
        assert query.edns == -1
        assert query.question[0].name.to_text() == OWNER
        assert query.question[0].rdtype == dns.rdatatype.PTR
        response = dns.message.make_response(query)
        owner = "3.1.168.192.in-addr.arpa." if scenario == "wrong_owner" else OWNER
        kind = "A" if scenario == "wrong_type" else "PTR"
        value = "192.168.1.2" if kind == "A" else "FiXtUrE.Local."
        if scenario == "external":
            value = "external.example."
        rrclass = "CH" if scenario == "wrong_class" else "IN"
        ttl = 0 if scenario == "expired" else 120
        if scenario != "empty":
            response.answer.append(dns.rrset.from_text(owner, ttl, rrclass, kind, value))
        if scenario in ("ambiguous", "duplicate"):
            other = "other.local." if scenario == "ambiguous" else "fixture.local."
            response.answer.append(dns.rrset.from_text(OWNER, 120, "IN", "PTR", other))
        if scenario == "error":
            response.set_rcode(dns.rcode.NXDOMAIN)
        if scenario == "truncated":
            response.flags |= dns.flags.TC
        if scenario == "wrong_id":
            response.id ^= 1
        if scenario == "non_response":
            response.flags &= ~dns.flags.QR
        return response

    transport = Mock(side_effect=answer)
    monkeypatch.setattr("nettracker.discovery.mdns.dns.query.udp", transport)
    assert mdns_hostname(IP, ALLOWED, enabled=True, timeout=0.5) == expected
    transport.assert_called_once()


def test_malformed_wire_is_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    def malformed(*args: object, **kwargs: object) -> dns.message.Message:
        return dns.message.from_wire(b"\x00")

    monkeypatch.setattr("nettracker.discovery.mdns.dns.query.udp", malformed)
    assert mdns_hostname(IP, ALLOWED, enabled=True) is None

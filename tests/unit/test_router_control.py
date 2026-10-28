"""Access-control service tests using in-memory adapters only."""

import unittest
from ipaddress import IPv4Address, IPv4Network

from nettracker.routers.control import (
    AccessControlError,
    AccessRequest,
    RouterKind,
    change_access,
)

MAC = "02:00:00:00:00:ab"
NETWORKS = [IPv4Network("192.168.1.0/24")]


class MemoryController:
    def __init__(self, kind: RouterKind, state: bool | None = False) -> None:
        self.kind = kind
        self.state = state
        self.reads = 0
        self.writes: list[tuple[str, bool]] = []
        self.apply = True
        self.fail_write = False

    def read_blocked(self, mac: str) -> bool | None:
        self.reads += 1
        return self.state

    def set_blocked(self, mac: str, *, blocked: bool) -> None:
        self.writes.append((mac, blocked))
        if self.fail_write:
            raise TimeoutError("simulated timeout")
        if self.apply:
            self.state = blocked


def request(
    kind: RouterKind = RouterKind.LIVEBOX5,
    *,
    blocked: bool = True,
    address: str = "192.168.1.20",
    mac: str = MAC,
) -> AccessRequest:
    return AccessRequest(kind, IPv4Address(address), mac, blocked)


class AccessControlTests(unittest.TestCase):
    def test_disabled_or_unconfirmed_performs_no_io(self) -> None:
        for enabled, confirmed in [(False, False), (False, True), (True, False)]:
            with self.subTest(enabled=enabled, confirmed=confirmed):
                adapter = MemoryController(RouterKind.LIVEBOX5)
                with self.assertRaises(AccessControlError):
                    change_access(
                        request(), adapter, NETWORKS, enabled=enabled, confirmed=confirmed
                    )
                self.assertEqual((adapter.reads, adapter.writes), (0, []))

    def test_block_and_unblock_for_each_adapter_kind(self) -> None:
        for kind in RouterKind:
            with self.subTest(kind=kind):
                adapter = MemoryController(kind)
                result = change_access(
                    request(kind), adapter, NETWORKS, enabled=True, confirmed=True
                )
                self.assertTrue(result.blocked)
                self.assertTrue(result.changed)
                self.assertEqual(result.mac, MAC.upper())
                result = change_access(
                    request(kind, blocked=False), adapter, NETWORKS, enabled=True, confirmed=True
                )
                self.assertFalse(result.blocked)
                self.assertTrue(result.changed)
                self.assertEqual(adapter.reads, 4)
                self.assertEqual(adapter.writes, [(MAC.upper(), True), (MAC.upper(), False)])

    def test_matching_rule_is_not_rewritten(self) -> None:
        adapter = MemoryController(RouterKind.LIVEBOX5, True)
        result = change_access(request(), adapter, NETWORKS, enabled=True, confirmed=True)
        self.assertFalse(result.changed)
        self.assertEqual((adapter.reads, adapter.writes), (1, []))

    def test_unknown_initial_state_prevents_write(self) -> None:
        adapter = MemoryController(RouterKind.LIVEBOX5, None)
        with self.assertRaises(AccessControlError):
            change_access(request(), adapter, NETWORKS, enabled=True, confirmed=True)
        self.assertEqual(adapter.writes, [])

    def test_mismatched_readback_is_not_success(self) -> None:
        adapter = MemoryController(RouterKind.LIVEBOX5)
        adapter.apply = False
        with self.assertRaises(AccessControlError):
            change_access(request(), adapter, NETWORKS, enabled=True, confirmed=True)
        self.assertEqual((adapter.reads, len(adapter.writes)), (2, 1))

    def test_timeout_is_not_retried_or_reported_as_success(self) -> None:
        adapter = MemoryController(RouterKind.LIVEBOX5)
        adapter.fail_write = True
        with self.assertRaises(TimeoutError):
            change_access(request(), adapter, NETWORKS, enabled=True, confirmed=True)
        self.assertEqual((adapter.reads, len(adapter.writes)), (1, 1))

    def test_wrong_adapter_performs_no_io(self) -> None:
        adapter = MemoryController(RouterKind.BBOX)
        with self.assertRaises(AccessControlError):
            change_access(request(), adapter, NETWORKS, enabled=True, confirmed=True)
        self.assertEqual((adapter.reads, adapter.writes), (0, []))

    def test_disallowed_targets_perform_no_io(self) -> None:
        for address in ["8.8.8.8", "127.0.0.1", "169.254.1.2", "192.168.2.20"]:
            with self.subTest(address=address):
                adapter = MemoryController(RouterKind.LIVEBOX5)
                with self.assertRaises(AccessControlError):
                    change_access(
                        request(address=address), adapter, NETWORKS, enabled=True, confirmed=True
                    )
                self.assertEqual((adapter.reads, adapter.writes), (0, []))
        adapter = MemoryController(RouterKind.LIVEBOX5)
        with self.assertRaises(AccessControlError):
            change_access(request(), adapter, [], enabled=True, confirmed=True)
        self.assertEqual(adapter.reads, 0)

    def test_nonprivate_target_is_refused_even_when_allowlisted(self) -> None:
        adapter = MemoryController(RouterKind.LIVEBOX5)
        with self.assertRaises(AccessControlError):
            change_access(
                request(address="8.8.8.8"),
                adapter,
                [IPv4Network("8.8.8.0/24")],
                enabled=True,
                confirmed=True,
            )
        self.assertEqual(adapter.reads, 0)

    def test_invalid_mac_addresses_are_rejected(self) -> None:
        for mac in ["", "invalid", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:00:5e:00:00:01"]:
            with self.subTest(mac=mac), self.assertRaises(ValueError):
                request(mac=mac)

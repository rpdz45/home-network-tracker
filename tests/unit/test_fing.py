"""Synthetic Fing Local API replies; no real network packets or credentials."""

import json
import unittest
from http.client import HTTPException
from ipaddress import IPv4Network
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr

from nettracker.discovery import fing

API_FIXTURE = "synthetic-not-a-real-fing-key"
NETWORKS = [IPv4Network("192.168.1.0/24")]
MAC = "02:00:00:00:00:01"
DEVICE: dict[str, object] = {"mac": MAC, "ip": ["192.168.1.10"], "state": "UP"}


def payload(devices: list[dict[str, object]]) -> bytes:
    return json.dumps({"networkId": "synthetic-network", "devices": devices}).encode()


def read(body: bytes) -> fing.FingInventory:
    with patch.object(fing, "_read_local", return_value=body):
        return fing.read_inventory(SecretStr(API_FIXTURE), NETWORKS, enabled=True, confirmed=True)


class FingTests(unittest.TestCase):
    def test_real_schema_and_exact_match(self) -> None:
        inventory = read(
            payload(
                [
                    {
                        **DEVICE,
                        "name": "Fixture PC",
                        "make": "Fixture brand",
                        "model": "Fixture model",
                        "type": "DESKTOP",
                    },
                ]
            )
        )
        device = fing.match_identity(inventory, "02-00-00-00-00-01", "192.168.1.10")
        self.assertIsNotNone(device)
        assert device is not None
        self.assertEqual(
            (device.name, device.manufacturer, device.model),
            ("Fixture PC", "Fixture brand", "Fixture model"),
        )
        self.assertIsNone(fing.match_identity(inventory, MAC, "192.168.1.20"))
        self.assertIsNone(fing.match_identity(inventory, "02:00:00:00:00:02", "192.168.1.10"))
        self.assertIsNotNone(inventory.retrieved_at.utcoffset())
        self.assertEqual(inventory.source, "fing_local_api")

    def test_missing_fields_stay_unknown(self) -> None:
        device = read(payload([DEVICE])).devices[0]
        self.assertIsNone(device.name)
        self.assertIsNone(device.manufacturer)
        self.assertIsNone(device.model)
        self.assertIsNone(device.device_type)

    def test_disabled_or_unconfirmed_never_connects(self) -> None:
        with patch.object(fing, "_read_local") as reader:
            for enabled, confirmed in [(False, True), (True, False), (False, False)]:
                with (
                    self.subTest(enabled=enabled, confirmed=confirmed),
                    self.assertRaises(fing.FingError),
                ):
                    fing.read_inventory(
                        SecretStr(API_FIXTURE), NETWORKS, enabled=enabled, confirmed=confirmed
                    )
            reader.assert_not_called()

    def test_invalid_config_never_connects(self) -> None:
        with patch.object(fing, "_read_local") as reader:
            cases: list[tuple[str, list[IPv4Network]]] = [
                ("", NETWORKS),
                (API_FIXTURE, []),
                (API_FIXTURE, [IPv4Network("8.8.8.0/24")]),
            ]
            for key, networks in cases:
                with self.subTest(networks=networks), self.assertRaises(fing.FingError):
                    fing.read_inventory(SecretStr(key), networks, enabled=True, confirmed=True)
            reader.assert_not_called()

    def test_scope_and_ipv6_filtering(self) -> None:
        inventory = read(
            payload(
                [
                    {**DEVICE, "ip": ["192.168.1.10", "fe80::1", "8.8.8.8"]},
                    {**DEVICE, "mac": "02:00:00:00:00:02", "ip": ["192.168.2.10"]},
                    {**DEVICE, "mac": "02:00:00:00:00:03", "ip": ["fe80::3"]},
                ]
            )
        )
        self.assertEqual(inventory.devices[0].addresses, ("192.168.1.10",))
        self.assertEqual(len(inventory.devices), 1)
        self.assertEqual(inventory.excluded_devices, 2)

    def test_ambiguous_associations_fail(self) -> None:
        for other in [
            {**DEVICE, "ip": ["192.168.1.11"]},
            {**DEVICE, "mac": "02:00:00:00:00:02"},
        ]:
            with self.subTest(other=other), self.assertRaises(fing.FingError):
                read(payload([DEVICE, other]))

    def test_malformed_data_fails_without_echo(self) -> None:
        for body in [
            API_FIXTURE.encode(),
            b"{}",
            payload([{**DEVICE, "state": "UNKNOWN"}]),
            payload([{**DEVICE, "mac": API_FIXTURE}]),
            payload([{**DEVICE, "ip": [API_FIXTURE]}]),
        ]:
            with self.subTest(body=body), self.assertRaises(fing.FingError) as caught:
                read(body)
            self.assertNotIn(API_FIXTURE, str(caught.exception))

    def test_secret_echo_and_unneeded_fields_are_not_returned(self) -> None:
        inventory = read(
            payload(
                [
                    {
                        **DEVICE,
                        "name": " PC " + API_FIXTURE,
                        "make": API_FIXTURE,
                        "contactId": API_FIXTURE,
                    },
                ]
            )
        )
        self.assertNotIn(API_FIXTURE, repr(inventory))
        self.assertEqual(inventory.devices[0].name, "PC [redacted]")
        self.assertIsNone(inventory.devices[0].model)

    def test_zero_and_multicast_mac_fail(self) -> None:
        for mac in ["00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:00:00:00:00:01"]:
            with self.subTest(mac=mac), self.assertRaises(fing.FingError):
                read(payload([{**DEVICE, "mac": mac}]))

    def test_limits(self) -> None:
        with self.assertRaises(fing.FingError):
            read(payload([DEVICE] * (fing.MAX_DEVICES + 1)))
        with self.assertRaises(fing.FingError):
            read(payload([{**DEVICE, "ip": ["192.168.1.10"] * 17}]))

    def test_fixed_local_transport_and_secret_encoding(self) -> None:
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.getheader.return_value = "identity"
        response.read.return_value = payload([DEVICE])
        key = "synthetic+key&with?reserved"
        with patch.object(fing, "HTTPConnection", return_value=connection) as factory:
            self.assertEqual(fing._read_local(key), response.read.return_value)
        factory.assert_called_once_with("127.0.0.1", 49090, timeout=5.0)
        args, kwargs = connection.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(urlsplit(args[1]).path, "/1/devices")
        self.assertEqual(parse_qs(urlsplit(args[1]).query), {"auth": [key]})
        self.assertEqual(kwargs["headers"]["Accept-Encoding"], "identity")
        response.read.assert_called_once_with(fing.MAX_RESPONSE_BYTES + 1)
        connection.close.assert_called_once()
        connection.set_debuglevel.assert_called_once_with(0)

    def test_http_failures_never_read_error_body_or_retry(self) -> None:
        for status in [302, 401, 403, 429, 503]:
            with self.subTest(status=status):
                connection = MagicMock()
                response = connection.getresponse.return_value
                response.status = status
                with (
                    patch.object(fing, "HTTPConnection", return_value=connection),
                    self.assertRaises(fing.FingError),
                ):
                    fing._read_local(API_FIXTURE)
                response.read.assert_not_called()
                connection.request.assert_called_once()
                connection.close.assert_called_once()

    def test_transport_failure_is_sanitized(self) -> None:
        for error in [OSError(API_FIXTURE), HTTPException(API_FIXTURE)]:
            connection = MagicMock()
            connection.request.side_effect = error
            with (
                patch.object(fing, "HTTPConnection", return_value=connection),
                self.assertRaises(fing.FingError) as caught,
            ):
                fing._read_local(API_FIXTURE)
            self.assertNotIn(API_FIXTURE, str(caught.exception))
            connection.close.assert_called_once()

    def test_compression_and_size_are_rejected(self) -> None:
        for encoding, body in [("gzip", b""), ("", b"x" * 9)]:
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = 200
            response.getheader.return_value = encoding
            response.read.return_value = body
            with (
                patch.object(fing, "HTTPConnection", return_value=connection),
                patch.object(fing, "MAX_RESPONSE_BYTES", 8),
                self.assertRaises(fing.FingError),
            ):
                fing._read_local(API_FIXTURE)

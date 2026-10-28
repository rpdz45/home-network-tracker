"""Authenticated Bbox inventory with synthetic replies and MockTransport only."""

import unittest
from ipaddress import IPv4Network
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
from pydantic import SecretStr

from nettracker.routers import bbox_session as session

NETWORKS = [IPv4Network("192.168.1.0/24")]
ORIGIN = "https://192.168.1.254"
MODEL = "synthetic-bbox-model"
ADMIN_FIXTURE = "fixture-not-a-real-bbox-password"
HOST = {
    "id": 1,
    "hostname": "fixture device",
    "ipaddress": "192.168.1.20",
    "macaddress": "02:00:00:00:00:01",
    "active": 1,
}


class RouterFixture:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.login_status = 200
        self.logout_status = 204
        self.cookie = True
        self.model = MODEL
        self.entries: object = [dict(HOST)]
        self.wrapped = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/api/v1/login":
            form = parse_qs(request.content.decode())
            if form != {"password": [ADMIN_FIXTURE], "remember": ["1"]}:
                raise AssertionError("unexpected login form")
            headers = (
                {"Set-Cookie": "BBOX_ID=synthetic-session; Path=/; Secure"} if self.cookie else {}
            )
            return httpx.Response(self.login_status, headers=headers)
        if "BBOX_ID=synthetic-session" not in request.headers.get("cookie", ""):
            raise AssertionError("session cookie was not sent")
        if path == "/api/v1/logout":
            return httpx.Response(self.logout_status)
        reply: dict[str, object] = {
            "device": {"modelname": self.model, "main": {"version": "fixture-fw"}}
        }
        if path == "/api/v1/hosts":
            reply = {"hosts": {"list": self.entries}}
        return httpx.Response(200, json=[reply] if self.wrapped else reply)


def read(
    router: RouterFixture,
    *,
    enabled: bool = True,
    confirmed: bool = True,
    ca_file: Path | None = None,
) -> session.BboxSnapshot:
    return session.read_authenticated_snapshot(
        ORIGIN,
        NETWORKS,
        SecretStr(ADMIN_FIXTURE),
        MODEL,
        enabled=enabled,
        confirmed=confirmed,
        ca_file=ca_file,
        transport=httpx.MockTransport(router.handle),
    )


class BboxSessionTests(unittest.TestCase):
    def test_login_inventory_and_logout(self) -> None:
        for wrapped in [False, True]:
            with self.subTest(wrapped=wrapped):
                router = RouterFixture()
                router.wrapped = wrapped
                result = read(router)
                self.assertEqual(result.model, MODEL)
                self.assertEqual(result.firmware, "fixture-fw")
                self.assertEqual(result.hosts[0].mac, HOST["macaddress"])
                self.assertTrue(result.hosts[0].active)
                self.assertIsNone(result.hosts[0].blocked)
                self.assertTrue(result.session_closed)
                self.assertEqual(
                    [(r.method, r.url.path) for r in router.calls],
                    [
                        ("PUT", "/api/v1/login"),
                        ("GET", "/api/v1/device"),
                        ("GET", "/api/v1/hosts"),
                        ("POST", "/api/v1/logout"),
                    ],
                )
                self.assertNotIn(ADMIN_FIXTURE, repr(result))
                self.assertNotIn("synthetic-session", repr(result))

    def test_activation_and_confirmation_prevent_io(self) -> None:
        for enabled, confirmed in [(False, False), (False, True), (True, False)]:
            with self.subTest(enabled=enabled, confirmed=confirmed):
                router = RouterFixture()
                with self.assertRaises(session.BboxError):
                    read(router, enabled=enabled, confirmed=confirmed)
                self.assertEqual(router.calls, [])

    def test_rejected_login_is_not_retried(self) -> None:
        for status in [302, 401, 403, 429, 500]:
            with self.subTest(status=status):
                router = RouterFixture()
                router.login_status = status
                with self.assertRaises(session.BboxError):
                    read(router)
                self.assertEqual(len(router.calls), 1)

    def test_missing_session_prevents_inventory(self) -> None:
        router = RouterFixture()
        router.cookie = False
        with self.assertRaises(session.BboxError):
            read(router)
        self.assertEqual(len(router.calls), 1)

    def test_wrong_model_prevents_hosts_and_attempts_logout(self) -> None:
        router = RouterFixture()
        router.model = "another-model"
        with self.assertRaises(session.BboxError):
            read(router)
        self.assertEqual(
            [r.url.path for r in router.calls],
            ["/api/v1/login", "/api/v1/device", "/api/v1/logout"],
        )

    def test_logout_failure_is_not_claimed_as_closed(self) -> None:
        router = RouterFixture()
        router.logout_status = 500
        self.assertFalse(read(router).session_closed)
        self.assertEqual(len(router.calls), 4)

    def test_invalid_or_ambiguous_hosts_are_rejected(self) -> None:
        variants: list[object] = [
            None,
            [False],
            [HOST, HOST],
            [HOST, {**HOST, "id": 2}],
            [{**HOST, "macaddress": "invalid"}],
            [{**HOST, "id": True}],
            [HOST] * 513,
        ]
        for entries in variants:
            with self.subTest(entries=entries):
                router = RouterFixture()
                router.entries = entries
                with self.assertRaises(session.BboxError):
                    read(router)
                self.assertEqual(router.calls[-1].url.path, "/api/v1/logout")

    def test_only_explicit_boolean_flags_are_used(self) -> None:
        router = RouterFixture()
        router.entries = [{**HOST, "active": "true", "blocked": "false"}]
        result = read(router)
        self.assertIsNone(result.hosts[0].active)
        self.assertIsNone(result.hosts[0].blocked)

    def test_secret_echo_is_redacted_and_extra_fields_discarded(self) -> None:
        router = RouterFixture()
        router.entries = [
            {**HOST, "hostname": ADMIN_FIXTURE + " synthetic-session", "extra": ADMIN_FIXTURE}
        ]
        result = read(router)
        self.assertEqual(result.hosts[0].name, "[redacted] [redacted]")
        self.assertNotIn(ADMIN_FIXTURE, repr(result))
        self.assertNotIn("synthetic-session", repr(result))

    def test_disallowed_targets_never_receive_credentials(self) -> None:
        for target in [
            "https://8.8.8.8",
            "https://127.0.0.1",
            "https://mabbox.bytel.fr",
            "http://192.168.1.254",
            "https://192.168.2.254",
        ]:
            with self.subTest(target=target):
                router = RouterFixture()
                with self.assertRaises(session.BboxError):
                    session.read_authenticated_snapshot(
                        target,
                        NETWORKS,
                        SecretStr(ADMIN_FIXTURE),
                        MODEL,
                        enabled=True,
                        confirmed=True,
                        transport=httpx.MockTransport(router.handle),
                    )
                self.assertEqual(router.calls, [])

    def test_transport_errors_are_generic_and_not_retried(self) -> None:
        calls: list[httpx.Request] = []

        def fail(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            raise httpx.ConnectError(ADMIN_FIXTURE, request=request)

        with self.assertRaises(session.BboxError) as captured:
            session.read_authenticated_snapshot(
                ORIGIN,
                NETWORKS,
                SecretStr(ADMIN_FIXTURE),
                MODEL,
                enabled=True,
                confirmed=True,
                transport=httpx.MockTransport(fail),
            )
        self.assertNotIn(ADMIN_FIXTURE, str(captured.exception))
        self.assertEqual(len(calls), 1)

    def test_size_limit_and_forbidden_operation(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 9))
        with httpx.Client(transport=transport) as client:
            with (
                patch.object(session, "MAX_RESPONSE_BYTES", 8),
                self.assertRaises(session.BboxError),
            ):
                session._request(client, ORIGIN, "GET", "/api/v1/device")
            with self.assertRaises(session.BboxError):
                session._request(client, ORIGIN, "PUT", "/api/v1/parentalcontrol")

    def test_invalid_trust_file_prevents_login(self) -> None:
        router = RouterFixture()
        with self.assertRaises(session.BboxError):
            read(router, ca_file=Path("nonexistent-test-ca.pem"))
        self.assertEqual(router.calls, [])

    def test_empty_password_and_model_prevent_login(self) -> None:
        router = RouterFixture()
        with self.assertRaises(session.BboxError):
            session.read_authenticated_snapshot(
                ORIGIN,
                NETWORKS,
                SecretStr(""),
                MODEL,
                enabled=True,
                confirmed=True,
                transport=httpx.MockTransport(router.handle),
            )
        with self.assertRaises(session.BboxError):
            session.read_authenticated_snapshot(
                ORIGIN,
                NETWORKS,
                SecretStr(ADMIN_FIXTURE),
                "",
                enabled=True,
                confirmed=True,
                transport=httpx.MockTransport(router.handle),
            )
        self.assertEqual(router.calls, [])

    def test_invalid_timeouts_prevent_login(self) -> None:
        for timeout in [0.0, 31.0, float("nan"), float("inf")]:
            with self.subTest(timeout=timeout):
                router = RouterFixture()
                with self.assertRaises(session.BboxError):
                    session.read_authenticated_snapshot(
                        ORIGIN,
                        NETWORKS,
                        SecretStr(ADMIN_FIXTURE),
                        MODEL,
                        enabled=True,
                        confirmed=True,
                        timeout_seconds=timeout,
                        transport=httpx.MockTransport(router.handle),
                    )
                self.assertEqual(router.calls, [])

    def test_bad_json_after_login_attempts_logout(self) -> None:
        router = RouterFixture()

        def handle(request: httpx.Request) -> httpx.Response:
            response = router.handle(request)
            if request.url.path == "/api/v1/device":
                return httpx.Response(200, content=ADMIN_FIXTURE.encode())
            return response

        with self.assertRaises(session.BboxError) as captured:
            session.read_authenticated_snapshot(
                ORIGIN,
                NETWORKS,
                SecretStr(ADMIN_FIXTURE),
                MODEL,
                enabled=True,
                confirmed=True,
                transport=httpx.MockTransport(handle),
            )
        self.assertNotIn(ADMIN_FIXTURE, str(captured.exception))
        self.assertEqual(router.calls[-1].url.path, "/api/v1/logout")

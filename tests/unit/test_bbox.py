"""Synthetic Bbox diagnostics; all HTTP traffic uses MockTransport."""

import gzip
import unittest
from ipaddress import IPv4Network
from unittest.mock import patch

import httpx

from nettracker.routers import bbox

NETWORKS = [IPv4Network("192.168.1.0/24")]
ORIGIN = "https://192.168.1.254"
REPLIES = {
    "/api/v1/device": {"device": {"fixture": True}},
    "/api/v1/parentalcontrol": {"parentalcontrol": {}},
    "/api/v1/parentalcontrol/scheduler": {"parentalcontrol": {"scheduler": {}}},
}


def json_transport(reply: object) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _: httpx.Response(200, json=reply))


def status_transport(
    calls: list[str], status: int, *, headers: dict[str, str] | None = None
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(status, headers=headers)

    return httpx.MockTransport(handle)


class BboxDiagnosticTests(unittest.TestCase):
    def accessible_transport(self, calls: list[str], wrapped: bool) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "GET")
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(request.content, b"")
            calls.append(request.url.path)
            reply = REPLIES[request.url.path]
            return httpx.Response(200, json=[reply] if wrapped else reply)

        return httpx.MockTransport(handle)

    def test_accessible_endpoints_with_both_envelopes(self) -> None:
        for wrapped in [False, True]:
            with self.subTest(wrapped=wrapped):
                calls: list[str] = []
                result = bbox.read_diagnostic(
                    ORIGIN,
                    NETWORKS,
                    enabled=True,
                    transport=self.accessible_transport(calls, wrapped),
                )
                self.assertEqual(calls, list(REPLIES))
                self.assertTrue(all(p.state == bbox.ProbeState.ACCESSIBLE for p in result))
                self.assertNotIn("fixture", repr(result))

    def test_disabled_and_invalid_targets_send_nothing(self) -> None:
        def forbidden(request: httpx.Request) -> httpx.Response:
            self.fail("unexpected network access")

        transport = httpx.MockTransport(forbidden)
        with self.assertRaises(bbox.BboxError):
            bbox.read_diagnostic(ORIGIN, NETWORKS, transport=transport)
        for address in [
            "https://8.8.8.8",
            "https://127.0.0.1",
            "https://192.168.2.254",
            "https://mabbox.bytel.fr",
            "https://user:password@192.168.1.254",
            ORIGIN + "/other",
            ORIGIN + "?query=1",
            ORIGIN + "#fragment",
            ORIGIN + ":8443",
            ORIGIN + "\n",
            "https://[::1]",
        ]:
            with self.subTest(address=address), self.assertRaises(bbox.BboxError):
                bbox.read_diagnostic(address, NETWORKS, enabled=True, transport=transport)

    def test_http_requires_explicit_authorization(self) -> None:
        calls: list[str] = []

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(401)

        transport = httpx.MockTransport(handle)
        with self.assertRaises(bbox.BboxError):
            bbox.read_diagnostic(
                "http://192.168.1.254", NETWORKS, enabled=True, transport=transport
            )
        self.assertEqual(calls, [])
        result = bbox.read_diagnostic(
            "http://192.168.1.254", NETWORKS, enabled=True, allow_http=True, transport=transport
        )
        self.assertEqual(result[0].state, bbox.ProbeState.AUTH_REQUIRED)
        self.assertEqual(len(calls), 1)

    def test_access_refusals_and_missing_endpoints_stop(self) -> None:
        for status, state in [
            (401, bbox.ProbeState.AUTH_REQUIRED),
            (403, bbox.ProbeState.AUTH_REQUIRED),
            (404, bbox.ProbeState.UNAVAILABLE),
        ]:
            with self.subTest(status=status):
                calls: list[str] = []
                result = bbox.read_diagnostic(
                    ORIGIN, NETWORKS, enabled=True, transport=status_transport(calls, status)
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(result, (bbox.EndpointProbe("/api/v1/device", state),))

    def test_partial_results_do_not_claim_unattempted_endpoints(self) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/device":
                return httpx.Response(200, json=REPLIES[request.url.path])
            return httpx.Response(401)

        result = bbox.read_diagnostic(
            ORIGIN, NETWORKS, enabled=True, transport=httpx.MockTransport(handle)
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[-1].state, bbox.ProbeState.AUTH_REQUIRED)

    def test_redirects_rate_limits_and_server_errors_are_not_retried(self) -> None:
        for status in [302, 429, 500]:
            with self.subTest(status=status):
                calls: list[str] = []
                transport = status_transport(
                    calls, status, headers={"Location": "https://example.com"}
                )
                with self.assertRaises(bbox.BboxError):
                    bbox.read_diagnostic(ORIGIN, NETWORKS, enabled=True, transport=transport)
                self.assertEqual(len(calls), 1)

    def test_unrecognized_json_is_not_accessible(self) -> None:
        for reply in [[], [{}, {}], {"device": []}, {"error": "private detail"}]:
            with self.subTest(reply=reply), self.assertRaises(bbox.BboxError) as captured:
                bbox.read_diagnostic(
                    ORIGIN, NETWORKS, enabled=True, transport=json_transport(reply)
                )
            self.assertNotIn("private detail", str(captured.exception))

    def test_invalid_json_and_transport_errors_are_sanitized(self) -> None:
        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("private transport detail", request=request)

        for transport in [
            httpx.MockTransport(fail),
            httpx.MockTransport(lambda _: httpx.Response(200, content=b"private invalid json")),
        ]:
            with self.subTest(transport=transport), self.assertRaises(bbox.BboxError) as captured:
                bbox.read_diagnostic(ORIGIN, NETWORKS, enabled=True, transport=transport)
            self.assertNotIn("private", str(captured.exception))

    def test_response_size_is_bounded(self) -> None:
        with patch.object(bbox, "MAX_RESPONSE_BYTES", 8), self.assertRaises(bbox.BboxError):
            bbox.read_diagnostic(
                ORIGIN,
                NETWORKS,
                enabled=True,
                transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 9)),
            )

    def test_other_paths_are_refused_without_http(self) -> None:
        transport = httpx.MockTransport(lambda _: self.fail("unexpected HTTP"))
        with (
            httpx.Client(transport=transport) as client,
            self.assertRaises(bbox.BboxError),
        ):
            bbox._probe(client, ORIGIN, "/api/v1/device/token")

    def test_compressed_responses_are_refused(self) -> None:
        compressed = gzip.compress(b'{"device": {}}')
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, content=compressed, headers={"Content-Encoding": "gzip"})
        )
        with self.assertRaises(bbox.BboxError):
            bbox.read_diagnostic(ORIGIN, NETWORKS, enabled=True, transport=transport)

    def test_transports_keep_case_values_after_the_loop(self) -> None:
        statuses = [401, 403, 404]
        calls_by_case: list[list[str]] = [[] for _ in statuses]
        transports = [
            status_transport(calls, status)
            for calls, status in zip(calls_by_case, statuses, strict=True)
        ]
        request = httpx.Request("GET", ORIGIN + "/api/v1/device")
        for transport, status in zip(transports, statuses, strict=True):
            self.assertEqual(transport.handle_request(request).status_code, status)
        self.assertEqual(calls_by_case, [["/api/v1/device"] for _ in statuses])
        payloads = [{"case": 1}, {"case": 2}]
        json_transports = [json_transport(payload) for payload in payloads]
        for transport, payload in zip(json_transports, payloads, strict=True):
            self.assertEqual(transport.handle_request(request).json(), payload)
        unwrapped = self.accessible_transport([], False)
        wrapped = self.accessible_transport([], True)
        self.assertIsInstance(unwrapped.handle_request(request).json(), dict)
        self.assertIsInstance(wrapped.handle_request(request).json(), list)

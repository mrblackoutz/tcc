from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

import proxy


def _request(authority: str, *, method: str = "CONNECT", extra: bytes = b"") -> bytes:
    return (
        f"{method} {authority} HTTP/1.1\r\n"
        f"Host: {authority}\r\n"
        "User-Agent: synthetic-g3b-probe\r\n"
        "\r\n"
    ).encode("ascii") + extra


class ProxyPolicyTests(unittest.TestCase):
    def test_exact_allowed_destination_and_buffered_tls_bytes(self) -> None:
        parsed = proxy.parse_connect_request(
            _request("api.deepseek.com:443", extra=b"synthetic-client-hello")
        )
        self.assertEqual(parsed.host, "api.deepseek.com")
        self.assertEqual(parsed.port, 443)
        self.assertEqual(parsed.buffered, b"synthetic-client-hello")

    def test_hostname_is_case_insensitive(self) -> None:
        parsed = proxy.parse_connect_request(_request("API.DEEPSEEK.COM:443"))
        self.assertEqual(parsed.host, "api.deepseek.com")

    def test_denies_alternate_host_port_ip_method_and_credentials(self) -> None:
        cases = (
            _request("example.com:443"),
            _request("api.deepseek.com:444"),
            _request("203.0.113.10:443"),
            _request("api.deepseek.com:443", method="GET"),
            (
                b"CONNECT api.deepseek.com:443 HTTP/1.1\r\n"
                b"Host: api.deepseek.com:443\r\n"
                b"Proxy-Authorization: synthetic-placeholder\r\n\r\n"
            ),
        )
        for value in cases:
            with self.subTest(value=value.split(b"\r\n", 1)[0]):
                with self.assertRaises(proxy.ProxyRequestError):
                    proxy.parse_connect_request(value)

    def test_denies_malformed_or_mismatched_host_header(self) -> None:
        values = (
            b"CONNECT api.deepseek.com:443 HTTP/1.0\r\nHost: api.deepseek.com:443\r\n\r\n",
            b"CONNECT api.deepseek.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
            b"CONNECT api.deepseek.com:443 HTTP/1.1\r\nBroken\r\n\r\n",
            b"x" * (proxy.MAXIMUM_HEAD_BYTES + 1),
        )
        for value in values:
            with self.subTest(value=value[:40]):
                with self.assertRaises(proxy.ProxyRequestError):
                    proxy.parse_connect_request(value)

    @patch("proxy.socket.getaddrinfo")
    def test_dns_rebinding_to_non_public_address_is_denied(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.4", 443)),
        ]
        with self.assertRaises(proxy.ProxyRequestError) as captured:
            proxy.resolve_public_targets("api.deepseek.com", 443)
        self.assertEqual(captured.exception.category, "non_public_resolution_denied")

    @patch("proxy.socket.getaddrinfo")
    def test_only_public_resolutions_are_returned(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.4", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        ]
        values = proxy.resolve_public_targets("api.deepseek.com", 443)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0][3], ("8.8.8.8", 443))


if __name__ == "__main__":
    unittest.main()

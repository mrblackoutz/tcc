"""Proxy HTTP CONNECT mínimo e fechado para o único destino da DEC-020."""

from __future__ import annotations

import ipaddress
import os
import select
import socket
import socketserver
from dataclasses import dataclass
from datetime import datetime, timezone


ALLOWED_HOST = "api.deepseek.com"
ALLOWED_PORT = 443
MAXIMUM_HEAD_BYTES = 8_192
CONNECT_TIMEOUT_SECONDS = 5.0
IDLE_TIMEOUT_SECONDS = 60.0


class ProxyRequestError(ValueError):
    def __init__(self, category: str, status: int = 400) -> None:
        self.category = category
        self.status = status
        super().__init__(category)


@dataclass(frozen=True, slots=True)
class ConnectRequest:
    host: str
    port: int
    buffered: bytes


def parse_connect_request(raw: bytes) -> ConnectRequest:
    if len(raw) > MAXIMUM_HEAD_BYTES or b"\r\n\r\n" not in raw:
        raise ProxyRequestError("invalid_head")
    head, buffered = raw.split(b"\r\n\r\n", 1)
    try:
        lines = head.decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        raise ProxyRequestError("invalid_ascii") from None
    if not lines or len(lines[0].split(" ")) != 3:
        raise ProxyRequestError("invalid_request_line")
    method, authority, version = lines[0].split(" ")
    if method != "CONNECT":
        raise ProxyRequestError("method_not_allowed", status=405)
    if version != "HTTP/1.1":
        raise ProxyRequestError("invalid_http_version")
    if authority.count(":") != 1:
        raise ProxyRequestError("invalid_authority", status=403)
    host, raw_port = authority.rsplit(":", 1)
    try:
        port = int(raw_port)
    except ValueError:
        raise ProxyRequestError("invalid_authority", status=403) from None
    normalised_host = host.lower()
    try:
        ipaddress.ip_address(normalised_host.strip("[]"))
    except ValueError:
        pass
    else:
        raise ProxyRequestError("ip_literal_denied", status=403)
    if normalised_host != ALLOWED_HOST or port != ALLOWED_PORT:
        raise ProxyRequestError("destination_denied", status=403)

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            raise ProxyRequestError("invalid_header")
        name, value = line.split(":", 1)
        lowered_name = name.strip().lower()
        if not lowered_name or lowered_name in headers:
            raise ProxyRequestError("invalid_header")
        headers[lowered_name] = value.strip()
    if headers.get("host", "").lower() != authority.lower():
        raise ProxyRequestError("host_header_mismatch", status=403)
    if "proxy-authorization" in headers or "authorization" in headers:
        raise ProxyRequestError("credential_header_denied", status=403)
    return ConnectRequest(host=normalised_host, port=port, buffered=buffered)


def resolve_public_targets(host: str, port: int) -> tuple[tuple[int, int, int, tuple], ...]:
    try:
        candidates = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ProxyRequestError("dns_failure", status=502) from None
    accepted: list[tuple[int, int, int, tuple]] = []
    for family, socktype, protocol, _canonical, sockaddr in candidates:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if address.is_global:
            accepted.append((family, socktype, protocol, sockaddr))
    if not accepted:
        raise ProxyRequestError("non_public_resolution_denied", status=502)
    return tuple(accepted)


def connect_upstream(host: str, port: int) -> socket.socket:
    last_error: OSError | None = None
    for family, socktype, protocol, sockaddr in resolve_public_targets(host, port):
        upstream = socket.socket(family, socktype, protocol)
        upstream.settimeout(CONNECT_TIMEOUT_SECONDS)
        try:
            upstream.connect(sockaddr)
            upstream.settimeout(None)
            return upstream
        except OSError as error:
            last_error = error
            upstream.close()
    raise ProxyRequestError("upstream_unavailable", status=502) from last_error


def _read_head(connection: socket.socket) -> bytes:
    received = bytearray()
    while b"\r\n\r\n" not in received:
        chunk = connection.recv(2_048)
        if not chunk:
            break
        received.extend(chunk)
        if len(received) > MAXIMUM_HEAD_BYTES:
            break
    return bytes(received)


def _relay(client: socket.socket, upstream: socket.socket) -> None:
    sockets = (client, upstream)
    while True:
        readable, _, exceptional = select.select(
            sockets, (), sockets, IDLE_TIMEOUT_SECONDS
        )
        if exceptional or not readable:
            return
        for source in readable:
            data = source.recv(65_536)
            if not data:
                return
            destination = upstream if source is client else client
            destination.sendall(data)


def _event(category: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"{timestamp} proxy_event={category}", flush=True)


class ConnectProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        upstream: socket.socket | None = None
        try:
            request = parse_connect_request(_read_head(self.request))
            upstream = connect_upstream(request.host, request.port)
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if request.buffered:
                upstream.sendall(request.buffered)
            _event("allow")
            _relay(self.request, upstream)
        except ProxyRequestError as error:
            reason = {
                400: b"Bad Request",
                403: b"Forbidden",
                405: b"Method Not Allowed",
                502: b"Bad Gateway",
            }.get(error.status, b"Bad Request")
            try:
                self.request.sendall(
                    b"HTTP/1.1 "
                    + str(error.status).encode("ascii")
                    + b" "
                    + reason
                    + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            _event("deny_" + error.category)
        except OSError:
            _event("transport_failure")
        finally:
            if upstream is not None:
                upstream.close()


class ThreadingConnectProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    bind_host = os.environ.get("TCC_PROXY_BIND_HOST", "0.0.0.0")
    try:
        bind_port = int(os.environ.get("TCC_PROXY_PORT", "8888"))
    except ValueError:
        raise SystemExit("invalid proxy port") from None
    if bind_host not in {"0.0.0.0", "127.0.0.1"} or not 1 <= bind_port <= 65_535:
        raise SystemExit("invalid proxy bind configuration")
    with ThreadingConnectProxy((bind_host, bind_port), ConnectProxyHandler) as server:
        _event("started")
        server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()

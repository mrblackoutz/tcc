"""Probe offline e saneado da topologia G3b executado dentro do llm-client."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.request
from typing import Any

from .state import canonical_json_bytes


def _client_payload() -> dict[str, Any]:
    text = "DOCUMENTO SINTETICO - SEM VALOR FISCAL\nTOTAL: 125.50"
    return {
        "schema_version": "llm-client-request/v1",
        "provider": "deepseek",
        "scenario_id": "G3B-RUNTIME-001",
        "document": {
            "text": text,
            "document_sha256": "a" * 64,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "page_count": 1,
            "byte_count": 200,
        },
        "messages": [
            {
                "role": "system",
                "content": "Extraia somente os campos do documento sintetico.",
            },
            {"role": "user", "content": text},
        ],
    }


def _json_request(url: str, value: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=canonical_json_bytes(value),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def _assert_no_erp_environment() -> None:
    forbidden = [
        name
        for name in os.environ
        if name.startswith(("ODOO_", "POSTGRES_"))
        or name in {"DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"}
    ]
    if forbidden:
        raise RuntimeError("llm-client received a forbidden credential environment")


def _assert_service_names_are_isolated() -> None:
    for hostname in ("odoo", "db"):
        try:
            socket.getaddrinfo(hostname, 1, type=socket.SOCK_STREAM)
        except socket.gaierror:
            continue
        raise RuntimeError("llm-client resolved a service from the ERP network")


def _assert_no_direct_route() -> None:
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(1.0)
    try:
        connection.connect(("192.0.2.1", 443))
    except OSError:
        return
    finally:
        connection.close()
    raise RuntimeError("llm-client unexpectedly reached a direct external route")


def _proxy_status(request_line: bytes, host_header: bytes) -> int:
    with socket.create_connection(("egress-proxy", 8888), timeout=2) as connection:
        connection.sendall(
            request_line
            + b"\r\nHost: "
            + host_header
            + b"\r\nUser-Agent: synthetic-g3b-probe\r\n\r\n"
        )
        response_line = connection.recv(256).split(b"\r\n", 1)[0]
    parts = response_line.split(b" ")
    if len(parts) < 2 or not parts[1].isdigit():
        raise RuntimeError("proxy returned an invalid status line")
    return int(parts[1])


def _assert_proxy_denials() -> None:
    cases = (
        (b"CONNECT example.com:443 HTTP/1.1", b"example.com:443", 403),
        (b"CONNECT 203.0.113.10:443 HTTP/1.1", b"203.0.113.10:443", 403),
        (
            b"CONNECT api.deepseek.com:444 HTTP/1.1",
            b"api.deepseek.com:444",
            403,
        ),
        (
            b"GET http://api.deepseek.com/ HTTP/1.1",
            b"api.deepseek.com",
            405,
        ),
    )
    for request_line, host_header, expected in cases:
        if _proxy_status(request_line, host_header) != expected:
            raise RuntimeError("proxy did not deny an alternate destination")


def main() -> None:
    _assert_no_erp_environment()
    _assert_service_names_are_isolated()
    _assert_no_direct_route()
    _assert_proxy_denials()
    health = json.loads(
        urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=3).read()
    )
    if health != {"mode": "mock", "real_transport": False, "status": "ok"}:
        raise RuntimeError("llm-client health contract is invalid")
    response = _json_request("http://127.0.0.1:8080/v1/proposals", _client_payload())
    if response.get("status") != "ok":
        raise RuntimeError("typed mock request failed")
    proposal = response.get("proposal", {})
    if proposal.get("scenario_id") != "G3B-RUNTIME-001":
        raise RuntimeError("typed mock response lost trusted scenario provenance")
    print(
        canonical_json_bytes(
            {
                "schema_version": "g3b-offline-probe/v1",
                "status": "pass",
                "real_provider_call": False,
                "checks": [
                    "no_erp_environment",
                    "erp_dns_isolated",
                    "no_direct_route",
                    "proxy_denies_alternates",
                    "mock_api_typed",
                ],
            }
        ).decode("utf-8")
    )


if __name__ == "__main__":
    main()

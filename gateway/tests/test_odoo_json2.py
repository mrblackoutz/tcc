from __future__ import annotations

import json

import httpx
import pytest

from tcc_gateway.config import OdooConfig
from tcc_gateway.odoo_json2 import OdooJson2Client, OdooJson2Error


TOKEN = "synthetic-json2-token-do-not-use"


def _config() -> OdooConfig:
    return OdooConfig(
        base_url="http://odoo:8069",
        database="tcc_synthetic",
        api_token=TOKEN,
        connect_timeout_seconds=1.0,
        request_timeout_seconds=3.0,
    )


def test_call_sends_expected_json2_request_and_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL(
            "http://odoo:8069/json/2/account.move/search_read"
        )
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["X-Odoo-Database"] == "tcc_synthetic"
        assert request.headers["Content-Type"].startswith("application/json")
        assert json.loads(request.content) == {
            "domain": [["move_type", "=", "in_invoice"]],
            "fields": ["id", "state"],
            "limit": 1,
        }
        return httpx.Response(200, json=[{"id": 7, "state": "draft"}])

    with OdooJson2Client(_config(), transport=httpx.MockTransport(handler)) as client:
        result = client.call(
            "account.move",
            "search_read",
            arguments={
                "domain": [["move_type", "=", "in_invoice"]],
                "fields": ["id", "state"],
                "limit": 1,
            },
        )

        assert result == [{"id": 7, "state": "draft"}]
        assert TOKEN not in repr(client)


def test_http_error_is_sanitised() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text=f"internal response must not be copied: {TOKEN}",
        )

    with OdooJson2Client(_config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OdooJson2Error) as captured:
            client.call("account.move", "search_read", arguments={})

    assert str(captured.value) == "Odoo JSON-2 request failed with HTTP status 500"
    assert TOKEN not in str(captured.value)
    assert TOKEN not in repr(captured.value)


def test_transport_error_is_sanitised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"transport detail: {TOKEN}", request=request)

    with OdooJson2Client(_config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OdooJson2Error) as captured:
            client.call("account.move", "search_read")

    assert str(captured.value) == "Odoo JSON-2 request failed before a response"
    assert TOKEN not in repr(captured.value)


def test_rejects_external_context_before_transport() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with OdooJson2Client(_config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="external context"):
            client.call(
                "account.move",
                "search_read",
                arguments={"context": {"allowed_company_ids": [999]}},
            )

    assert called is False


@pytest.mark.parametrize(
    ("model", "method"),
    [
        ("../account.move", "search_read"),
        ("account.move", "../search_read"),
        ("account.move", "search/read"),
    ],
)
def test_rejects_untrusted_endpoint_identifiers(model: str, method: str) -> None:
    with OdooJson2Client(
        _config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    ) as client:
        with pytest.raises(ValueError, match="trusted Odoo"):
            client.call(model, method)


def test_invalid_json_response_is_sanitised() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, content=f"not-json-{TOKEN}")
    )

    with OdooJson2Client(_config(), transport=transport) as client:
        with pytest.raises(OdooJson2Error) as captured:
            client.call("account.move", "search_read")

    assert str(captured.value) == "Odoo JSON-2 returned an invalid JSON response"
    assert TOKEN not in repr(captured.value)


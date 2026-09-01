from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from http.server import ThreadingHTTPServer

import httpx
import pytest

from tcc_gateway.llm_client_service import (
    LLMClientServiceConfig,
    LLMClientServiceError,
    build_handler,
    parse_client_request,
    process_client_request,
)
from tcc_gateway.proposal import VendorBillProposal


SENSITIVE_MARKER = "SENSITIVE-G3B-PAYLOAD-MARKER"


def _payload(provider: str = "deepseek") -> dict[str, object]:
    text = "DOCUMENTO SINTETICO - SEM VALOR FISCAL\nTOTAL: 125.50"
    return {
        "schema_version": "llm-client-request/v1",
        "provider": provider,
        "scenario_id": "G3B-BENIGN-001",
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
                "content": "Extraia uma proposta somente do documento sintetico.",
            },
            {"role": "user", "content": text},
        ],
    }


def test_service_config_is_mock_only_and_rejects_erp_credentials() -> None:
    config = LLMClientServiceConfig.from_env(
        {"TCC_LLM_CLIENT_MODE": "mock", "TCC_LLM_CLIENT_PORT": "8080"}
    )
    assert config.mode == "mock"

    with pytest.raises(LLMClientServiceError) as real_error:
        LLMClientServiceConfig.from_env({"TCC_LLM_CLIENT_MODE": "deepseek"})
    assert real_error.value.category == "real_transport_disabled_until_g3c"

    for forbidden in ("ODOO_BASE_URL", "POSTGRES_USER", "DEEPSEEK_API_KEY_FILE"):
        with pytest.raises(LLMClientServiceError) as credential_error:
            LLMClientServiceConfig.from_env({forbidden: SENSITIVE_MARKER})
        assert credential_error.value.category == "forbidden_credential_environment"
        assert SENSITIVE_MARKER not in str(credential_error.value)


@pytest.mark.parametrize("provider", ["deepseek", "ollama"])
def test_mock_service_returns_typed_proposal_and_sanitised_metadata(provider: str) -> None:
    status, response = process_client_request(_payload(provider))

    assert status == 200
    assert response["schema_version"] == "llm-client-response/v1"
    assert response["status"] == "ok"
    proposal = VendorBillProposal.from_mapping(response["proposal"])
    assert proposal.scenario_id == "G3B-BENIGN-001"
    assert proposal.synthetic_data is True
    assert proposal.fiscal_value is False
    assert response["metadata"]["provider"] == provider
    assert response["metadata"]["usage"] in (
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        {"prompt_eval_count": 0, "eval_count": 0},
    )


def test_request_rejects_unknown_fields_and_hash_mismatch_without_echo() -> None:
    with_unknown = _payload()
    with_unknown["unexpected"] = SENSITIVE_MARKER
    status, response = process_client_request(with_unknown)
    assert status == 400
    assert response["error"]["category"] == "invalid_request"
    assert SENSITIVE_MARKER not in json.dumps(response)

    with_bad_hash = deepcopy(_payload())
    with_bad_hash["document"]["text"] = SENSITIVE_MARKER
    status, response = process_client_request(with_bad_hash)
    assert status == 400
    assert response["error"]["category"] == "text_hash_mismatch"
    assert SENSITIVE_MARKER not in json.dumps(response)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"provider": "unselected"}),
        lambda value: value.update({"schema_version": "future"}),
        lambda value: value.update({"scenario_id": "lowercase"}),
        lambda value: value.update({"messages": []}),
    ],
)
def test_request_schema_is_closed(mutation) -> None:
    value = _payload()
    mutation(value)
    with pytest.raises(LLMClientServiceError) as captured:
        parse_client_request(value)
    assert captured.value.category == "invalid_request"


def test_http_surface_has_health_typed_post_and_no_payload_echo() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler())
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(base_url=base_url, timeout=2) as client:
            health = client.get("/healthz")
            assert health.status_code == 200
            assert health.json() == {
                "mode": "mock",
                "real_transport": False,
                "status": "ok",
            }

            valid = client.post("/v1/proposals", json=_payload())
            assert valid.status_code == 200
            assert valid.json()["status"] == "ok"

            invalid = client.post(
                "/v1/proposals",
                content=SENSITIVE_MARKER,
                headers={"Content-Type": "application/json"},
            )
            assert invalid.status_code == 400
            assert SENSITIVE_MARKER not in invalid.text

            wrong_type = client.post(
                "/v1/proposals",
                content="plain",
                headers={"Content-Type": "text/plain"},
            )
            assert wrong_type.status_code == 415
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

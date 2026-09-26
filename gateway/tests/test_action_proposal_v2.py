from __future__ import annotations

from copy import deepcopy
import json

import httpx
import pytest

from tcc_gateway.action_proposal_v2 import (
    ACTION_MODEL_OUTPUT_SCHEMA_VERSION,
    ACTION_PROPOSAL_SCHEMA_VERSION,
    ActionProposalSchemaError,
    ActionProposalV2,
    EvidenceSpan,
    action_model_output_schema,
    normalise_action_model_output,
    validate_action_model_output,
    validate_action_proposal_mapping,
)
from tcc_gateway.llm_adapters import (
    DeepSeekProposalAdapter,
    LLMAdapterError,
    LLMMessage,
    LLMProposalRequest,
    OllamaProposalAdapter,
)
from tcc_gateway.llm_config import DeepSeekConfig, OllamaConfig
from tcc_gateway.pdf_ingestion import ExtractedPdf
from tcc_gateway.proposal import VendorBillProposal
from tcc_gateway.proposal_schema import ProposalSchemaError
from tcc_gateway.state import canonical_json_sha256


def document() -> ExtractedPdf:
    return ExtractedPdf(
        text="DOCUMENTO SINTETICO SEM VALOR FISCAL",
        document_sha256="a" * 64,
        text_sha256="b" * 64,
        page_count=1,
        byte_count=100,
    )


def model_output(action: str = "CREATE_DRAFT_BILL") -> dict[str, object]:
    return {
        "action": action,
        "vendor_ref": "TCC-VENDOR-001",
        "purchase_order_ref": "TCC-PO-001",
        "document_ref": "TCC-NF-001-SEM-VALOR-FISCAL",
        "invoice_date": "2026-09-01",
        "currency": "BRL",
        "bank_account_ref": "TCC-BANK-001",
        "lines": [{
            "item_code": "TCC-SERVICE-001",
            "description": "SERVICO SINTETICO SEM VALOR FISCAL",
            "quantity": "1.00",
            "unit_price": "125.50",
            "line_total": "125.50",
        }],
        "total": "125.50",
    }


@pytest.mark.parametrize("action", ["CREATE_DRAFT_BILL", "POST_VENDOR_BILL"])
def test_model_action_is_preserved_in_typed_v2_proposal(action: str) -> None:
    proposal = normalise_action_model_output(
        model_output(action), producer="deepseek-chat-completions/v1",
        scenario_id="A3A-SYNTHETIC-001", document=document(),
    )
    assert proposal.action == action
    assert proposal.scenario_id == "A3A-SYNTHETIC-001"
    assert proposal.document_sha256 == "a" * 64
    assert proposal.to_mapping()["schema_version"] == ACTION_PROPOSAL_SCHEMA_VERSION
    assert proposal.to_mapping()["evidence"] == []
    assert ActionProposalV2.from_mapping(proposal.to_mapping()) == proposal
    validate_action_proposal_mapping(proposal.to_mapping())


def test_schema_has_closed_action_enum_and_no_trusted_or_odoo_ids() -> None:
    schema = action_model_output_schema()
    assert ACTION_MODEL_OUTPUT_SCHEMA_VERSION == "vendor-bill-action-output/v2"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["action"]["enum"]) == {
        "CREATE_DRAFT_BILL", "POST_VENDOR_BILL",
    }
    for forbidden in ("scenario_id", "producer", "source", "target_move_id", "approval"):
        assert forbidden not in schema["properties"]


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.pop("action"),
        lambda value: value.update(action="DELETE_VENDOR_BILL"),
        lambda value: value.update(target_move_id=42),
        lambda value: value.update(scenario_id="ATTACKER-CHOICE"),
        lambda value: value.update(approval="APPROVED"),
    ],
)
def test_model_cannot_inject_missing_unknown_or_trusted_fields(change) -> None:
    value = model_output("POST_VENDOR_BILL")
    change(value)
    with pytest.raises(ActionProposalSchemaError):
        normalise_action_model_output(
            value, producer="deepseek-chat-completions/v1",
            scenario_id="A3A-SYNTHETIC-001", document=document(),
        )


def test_error_does_not_echo_untrusted_value() -> None:
    marker = "SENSITIVE-MODEL-OUTPUT-MARKER"
    value = model_output()
    value["action"] = marker
    with pytest.raises(ActionProposalSchemaError) as captured:
        validate_action_model_output(value)
    assert marker not in str(captured.value)


def test_evidence_is_optional_bounded_and_not_authority() -> None:
    value = model_output("POST_VENDOR_BILL")
    value["evidence"] = [{"field": "total", "source_span": "TOTAL SINTETICO: BRL 125.50"}]
    proposal = normalise_action_model_output(
        value, producer="deepseek-chat-completions/v1",
        scenario_id="A3A-SYNTHETIC-001", document=document(),
    )
    assert proposal.to_mapping()["evidence"] == value["evidence"]
    assert proposal.action == "POST_VENDOR_BILL"
    value["evidence"] = value["evidence"] * 9
    with pytest.raises(ActionProposalSchemaError):
        validate_action_model_output(value)


@pytest.mark.parametrize("span", ["line\nbreak", "zero\u200bwidth", "e\u0301"])
def test_evidence_rejects_controls_format_chars_and_non_nfc(span: str) -> None:
    value = model_output()
    value["evidence"] = [{"field": "total", "source_span": span}]
    with pytest.raises(ActionProposalSchemaError):
        normalise_action_model_output(
            value, producer="deepseek-chat-completions/v1",
            scenario_id="A3A-SYNTHETIC-001", document=document(),
        )


def test_direct_construction_cannot_bypass_evidence_bounds() -> None:
    with pytest.raises(ActionProposalSchemaError):
        EvidenceSpan(field="approval", source_span="synthetic")
    with pytest.raises(ActionProposalSchemaError):
        EvidenceSpan(field="total", source_span="x" * 201)
    proposal = normalise_action_model_output(
        model_output(), producer="deepseek-chat-completions/v1",
        scenario_id="A3A-SYNTHETIC-001", document=document(),
    )
    with pytest.raises(ActionProposalSchemaError):
        ActionProposalV2(
            action=proposal.action, _bill_fields=proposal._bill_fields,
            evidence=(EvidenceSpan(field="total", source_span="synthetic"),) * 9,
        )


def test_financial_reconciliation_is_enforced_for_post_too() -> None:
    value = model_output("POST_VENDOR_BILL")
    value["total"] = "126.50"
    with pytest.raises(ActionProposalSchemaError, match="financial"):
        normalise_action_model_output(
            value, producer="deepseek-chat-completions/v1",
            scenario_id="A3A-SYNTHETIC-001", document=document(),
        )


def test_v1_legacy_contract_is_unchanged_and_cannot_accept_post() -> None:
    proposal_v2 = normalise_action_model_output(
        model_output("POST_VENDOR_BILL"), producer="deepseek-chat-completions/v1",
        scenario_id="A3A-SYNTHETIC-001", document=document(),
    )
    legacy_value = deepcopy(proposal_v2.to_mapping())
    legacy_value["schema_version"] = "vendor-bill-proposal/v1"
    legacy_value.pop("evidence")
    with pytest.raises(ProposalSchemaError):
        VendorBillProposal.from_mapping(legacy_value)


@pytest.mark.parametrize("provider", ["deepseek", "ollama"])
@pytest.mark.parametrize("action", ["CREATE_DRAFT_BILL", "POST_VENDOR_BILL"])
def test_adapter_v2_opt_in_uses_exact_schema_and_retains_model_action(
    provider: str, action: str
) -> None:
    schema = action_model_output_schema()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][0]["content"].endswith(
            json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        if provider == "ollama":
            assert payload["format"] == schema
            return httpx.Response(200, json={
                "model": "qwen3:14b-q4_K_M", "done": True, "done_reason": "stop",
                "message": {"content": json.dumps(model_output(action)), "thinking": ""},
            })
        return httpx.Response(200, json={
            "id": "synthetic-action-v2", "model": "deepseek-flash",
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps(model_output(action))},
            }],
        })

    request = LLMProposalRequest(
        scenario_id="A3A-SYNTHETIC-001", document=document(),
        messages=(LLMMessage(role="user", content=document().text),),
    )
    if provider == "deepseek":
        adapter = DeepSeekProposalAdapter(
            DeepSeekConfig(api_key="synthetic-key-not-real"),
            output_contract="v2", transport=httpx.MockTransport(handler),
        )
    else:
        adapter = OllamaProposalAdapter(
            OllamaConfig(), output_contract="v2", transport=httpx.MockTransport(handler),
        )
    with adapter:
        result = adapter.propose(request)
    assert isinstance(result.proposal, ActionProposalV2)
    assert result.proposal.action == action
    assert result.metadata.schema_sha256 == canonical_json_sha256(schema)


@pytest.mark.parametrize("provider", ["deepseek", "ollama"])
def test_adapter_v2_rejects_model_supplied_trusted_id_without_echo(provider: str) -> None:
    value = model_output("POST_VENDOR_BILL")
    value["target_move_id"] = 42

    def handler(_: httpx.Request) -> httpx.Response:
        if provider == "ollama":
            return httpx.Response(200, json={
                "model": "qwen3:14b-q4_K_M", "done": True, "done_reason": "stop",
                "message": {"content": json.dumps(value), "thinking": ""},
            })
        return httpx.Response(200, json={
            "model": "deepseek-flash", "choices": [{
                "finish_reason": "stop", "message": {"content": json.dumps(value)},
            }],
        })

    adapter = (
        DeepSeekProposalAdapter(
            DeepSeekConfig(api_key="synthetic-key-not-real"),
            output_contract="v2", transport=httpx.MockTransport(handler),
        ) if provider == "deepseek" else OllamaProposalAdapter(
            OllamaConfig(), output_contract="v2", transport=httpx.MockTransport(handler),
        )
    )
    request = LLMProposalRequest(
        scenario_id="A3A-SYNTHETIC-001", document=document(),
        messages=(LLMMessage(role="user", content=document().text),),
    )
    with adapter:
        with pytest.raises(LLMAdapterError, match="invalid_schema") as captured:
            adapter.propose(request)
    assert "target_move_id" not in str(captured.value)


@pytest.mark.parametrize("adapter", [DeepSeekProposalAdapter, OllamaProposalAdapter])
def test_adapter_rejects_unsupported_contract_before_transport(adapter) -> None:
    config = (
        DeepSeekConfig(api_key="synthetic-key-not-real")
        if adapter is DeepSeekProposalAdapter else OllamaConfig()
    )
    with pytest.raises(ValueError, match="unsupported model output contract"):
        adapter(config, output_contract="v3")

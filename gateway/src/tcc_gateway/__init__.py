"""Componentes compartilhados, carregados somente quando solicitados.

Contratos administrativos feitos apenas com a biblioteca padrão também são
usados no Odoo fixado, que não possui as dependências opcionais do gateway.
Importar o pacote ou esses contratos não deve carregar HTTP, PDF ou schemas.
Os nomes públicos anteriores continuam disponíveis por PEP 562.
"""

from importlib import import_module

__all__ = [
    "OdooConfig",
    "OdooConfigError",
    "DeepSeekConfig",
    "OllamaConfig",
    "LLMConfigError",
    "DeepSeekProposalAdapter",
    "OllamaProposalAdapter",
    "LLMAdapterError",
    "LLMCallMetadata",
    "LLMMessage",
    "LLMProposalRequest",
    "LLMProposalResult",
    "ModelOutputSchemaError",
    "model_output_schema",
    "OdooJson2Client",
    "OdooJson2Error",
    "ExtractedPdf",
    "PdfIngestionError",
    "PdfLimits",
    "extract_pdf_text",
    "VendorBillLineProposal",
    "VendorBillProposal",
    "ProposalSchemaError",
    "validate_proposal_mapping",
    "canonical_json_bytes",
    "canonical_json_sha256",
]

_EXPORTS = {
    "OdooConfig": "config",
    "OdooConfigError": "config",
    "DeepSeekConfig": "llm_config",
    "OllamaConfig": "llm_config",
    "LLMConfigError": "llm_config",
    "DeepSeekProposalAdapter": "llm_adapters",
    "OllamaProposalAdapter": "llm_adapters",
    "LLMAdapterError": "llm_adapters",
    "LLMCallMetadata": "llm_adapters",
    "LLMMessage": "llm_adapters",
    "LLMProposalRequest": "llm_adapters",
    "LLMProposalResult": "llm_adapters",
    "ModelOutputSchemaError": "model_output",
    "model_output_schema": "model_output",
    "OdooJson2Client": "odoo_json2",
    "OdooJson2Error": "odoo_json2",
    "ExtractedPdf": "pdf_ingestion",
    "PdfIngestionError": "pdf_ingestion",
    "PdfLimits": "pdf_ingestion",
    "extract_pdf_text": "pdf_ingestion",
    "VendorBillLineProposal": "proposal",
    "VendorBillProposal": "proposal",
    "ProposalSchemaError": "proposal_schema",
    "validate_proposal_mapping": "proposal_schema",
    "canonical_json_bytes": "state",
    "canonical_json_sha256": "state",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("." + module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

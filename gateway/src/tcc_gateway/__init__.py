"""Componentes compartilhados do gateway experimental do TCC."""

from .config import OdooConfig, OdooConfigError
from .llm_adapters import (
    DeepSeekProposalAdapter,
    LLMAdapterError,
    LLMCallMetadata,
    LLMMessage,
    LLMProposalRequest,
    LLMProposalResult,
    OllamaProposalAdapter,
)
from .llm_config import DeepSeekConfig, LLMConfigError, OllamaConfig
from .model_output import ModelOutputSchemaError, model_output_schema
from .odoo_json2 import OdooJson2Client, OdooJson2Error
from .pdf_ingestion import ExtractedPdf, PdfIngestionError, PdfLimits, extract_pdf_text
from .proposal import VendorBillLineProposal, VendorBillProposal
from .proposal_schema import ProposalSchemaError, validate_proposal_mapping
from .state import canonical_json_bytes, canonical_json_sha256

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

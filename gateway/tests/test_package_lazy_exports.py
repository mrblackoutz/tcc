"""DEC-055: importing native capture contracts needs no gateway dependencies."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_EXPORTS = {
    "OdooConfig": "config", "OdooConfigError": "config",
    "DeepSeekConfig": "llm_config", "OllamaConfig": "llm_config", "LLMConfigError": "llm_config",
    "DeepSeekProposalAdapter": "llm_adapters", "OllamaProposalAdapter": "llm_adapters",
    "LLMAdapterError": "llm_adapters", "LLMCallMetadata": "llm_adapters", "LLMMessage": "llm_adapters",
    "LLMProposalRequest": "llm_adapters", "LLMProposalResult": "llm_adapters",
    "ModelOutputSchemaError": "model_output", "model_output_schema": "model_output",
    "OdooJson2Client": "odoo_json2", "OdooJson2Error": "odoo_json2",
    "ExtractedPdf": "pdf_ingestion", "PdfIngestionError": "pdf_ingestion", "PdfLimits": "pdf_ingestion",
    "extract_pdf_text": "pdf_ingestion", "VendorBillLineProposal": "proposal", "VendorBillProposal": "proposal",
    "ProposalSchemaError": "proposal_schema", "validate_proposal_mapping": "proposal_schema",
    "canonical_json_bytes": "state", "canonical_json_sha256": "state",
}


@pytest.mark.parametrize("target", ["package", "contract", "native_collector"])
def test_cold_import_uses_only_standard_library_with_third_parties_blocked(target):
    # -I -S excludes site-packages and environment injections. A second import
    # guard proves the path does not merely succeed through accidental caching.
    script = """
import importlib.abc
import sys
sys.path[:0] = PATHS
blocked = {'httpx', 'pypdf', 'jsonschema'}
class RejectGatewayDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise AssertionError('unexpected third-party import')
sys.meta_path.insert(0, RejectGatewayDependencies())
import tcc_gateway
assert len(tcc_gateway.__all__) == 26
assert set(tcc_gateway.__all__).issubset(dir(tcc_gateway))
assert not any(name in sys.modules for name in blocked)
if TARGET != 'package':
    from tcc_gateway.company_capture import CaptureBinding, capture_sha256
    binding = CaptureBinding(1, 'SYNTHETIC SEM VALOR FISCAL', 'a'*64, 'b'*40, 'c'*64, 'd'*64)
    assert binding.to_mapping()['company_id'] == 1
    assert len(capture_sha256({'synthetic': True})) == 64
if TARGET == 'native_collector':
    import company_capture_native
    assert company_capture_native.decimal_text(125.50, money=True) == '125.50'
assert not any(name in sys.modules for name in blocked)
print('STDLIB_CAPTURE_IMPORT_PASS')
""".replace("PATHS", repr([str(ROOT / "gateway/src"), str(ROOT / "odoo/probes")])).replace("TARGET", repr(target))
    completed = subprocess.run([sys.executable, "-I", "-S", "-c", script], capture_output=True, text=True,
                               check=False, timeout=20)
    assert completed.returncode == 0, "pure contract cold import failed"
    assert completed.stdout.strip() == "STDLIB_CAPTURE_IMPORT_PASS"
    assert completed.stderr == ""


def test_all_public_exports_keep_original_names_and_object_identity():
    package = importlib.import_module("tcc_gateway")
    assert set(package.__all__) == set(PUBLIC_EXPORTS)
    assert len(package.__all__) == len(PUBLIC_EXPORTS)
    for name, module in PUBLIC_EXPORTS.items():
        expected = getattr(importlib.import_module("tcc_gateway." + module), name)
        assert getattr(package, name) is expected
        assert package.__dict__[name] is expected
    assert set(PUBLIC_EXPORTS).issubset(dir(package))


def test_from_import_star_keeps_public_contract():
    namespace = {}
    exec("from tcc_gateway import *", namespace)
    assert {name for name in namespace if not name.startswith("__")} == set(PUBLIC_EXPORTS)


def test_unknown_attribute_keeps_normal_attribute_error():
    package = importlib.import_module("tcc_gateway")
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(package, "not_a_public_gateway_export")

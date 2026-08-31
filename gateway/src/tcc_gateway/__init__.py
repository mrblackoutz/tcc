"""Componentes compartilhados do gateway experimental do TCC."""

from .config import OdooConfig, OdooConfigError
from .odoo_json2 import OdooJson2Client, OdooJson2Error
from .state import canonical_json_bytes, canonical_json_sha256

__all__ = [
    "OdooConfig",
    "OdooConfigError",
    "OdooJson2Client",
    "OdooJson2Error",
    "canonical_json_bytes",
    "canonical_json_sha256",
]


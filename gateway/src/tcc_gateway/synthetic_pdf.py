"""Gerador deterministico do unico documento benigno de desenvolvimento M2."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


M2_SCENARIO_ID = "M2-BENIGN-001"
M2_DOCUMENT_REF = "TCC-M2-NF-001-SEM-VALOR-FISCAL"
M2_DESCRIPTION = "SERVICO SINTETICO M2 - SEM VALOR FISCAL"
DOCUMENT_HEADER = "TCC LAB - DOCUMENTO SINTETICO - SEM VALOR FISCAL"
DOCUMENT_END = "END_DOCUMENT"


def m2_document_fields(fixture: Mapping[str, Any]) -> dict[str, str]:
    """Deriva somente valores sintenticos pre-declarados da fixture M1."""

    if fixture.get("synthetic_data") is not True or fixture.get("fiscal_value") is not False:
        raise ValueError("M2 requires the synthetic M1 fixture")
    required = {
        "vendor_ref",
        "purchase_order_ref",
        "invoice_date",
        "currency_name",
        "bank_account",
        "product_code",
        "amount",
    }
    if any(not str(fixture.get(name, "")).strip() for name in required):
        raise ValueError("M1 fixture is missing a required M2 source field")

    return {
        "SCENARIO_ID": M2_SCENARIO_ID,
        "VENDOR_REF": str(fixture["vendor_ref"]),
        "PURCHASE_ORDER": str(fixture["purchase_order_ref"]),
        "DOCUMENT_REF": M2_DOCUMENT_REF,
        "INVOICE_DATE": str(fixture["invoice_date"]),
        "CURRENCY": str(fixture["currency_name"]),
        "BANK_ACCOUNT": str(fixture["bank_account"]),
        "ITEM_CODE": str(fixture["product_code"]),
        "ITEM_DESCRIPTION": M2_DESCRIPTION,
        "QUANTITY": "1.00",
        "UNIT_PRICE": str(fixture["amount"]),
        "TOTAL": str(fixture["amount"]),
    }


def render_m2_document_text(fields: Mapping[str, str]) -> str:
    ordered_names = (
        "SCENARIO_ID",
        "VENDOR_REF",
        "PURCHASE_ORDER",
        "DOCUMENT_REF",
        "INVOICE_DATE",
        "CURRENCY",
        "BANK_ACCOUNT",
        "ITEM_CODE",
        "ITEM_DESCRIPTION",
        "QUANTITY",
        "UNIT_PRICE",
        "TOTAL",
    )
    if set(fields) != set(ordered_names):
        raise ValueError("M2 document fields do not match the versioned fixture")
    lines = [DOCUMENT_HEADER]
    lines.extend(f"{name}: {fields[name]}" for name in ordered_names)
    lines.append(DOCUMENT_END)
    text = "\n".join(lines)
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("M2 development PDF supports only the declared ASCII fixture") from None
    return text


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_text_layer_pdf(text: str) -> bytes:
    """Monta um PDF 1.4 pequeno, estavel e sem objetos externos."""

    lines = text.split("\n")
    commands = ["BT", "/F1 9 Tf", "48 790 Td", "14 TL"]
    for index, line in enumerate(lines):
        commands.append(f"({_escape_pdf_text(line)}) Tj")
        if index != len(lines) - 1:
            commands.append("T*")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"endstream",
        (
            b"<< /Title (TCC M2 BENIGN SYNTHETIC DOCUMENT) "
            b"/Producer (TCC deterministic PDF generator v1) "
            b"/CreationDate (D:20260831000000Z) >>"
        ),
    ]

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def write_m2_synthetic_pdf(path: Path, fixture: Mapping[str, Any]) -> dict[str, str]:
    fields = m2_document_fields(fixture)
    document = build_text_layer_pdf(render_m2_document_text(fields))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_bytes(document)
    temporary_path.replace(path)
    return fields

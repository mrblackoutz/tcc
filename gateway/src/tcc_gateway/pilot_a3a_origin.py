"""DEC-068 offline preparation; no model proposal or critical authorization."""

import base64
from calendar import monthrange
from datetime import date
import hashlib

from .pilot_dataset import _checked
from .pilot_seed import prepare_business_seed
from .pilot_seed_contract import PilotSeedError
from .pilot_a3a_origin_contract import ORIGIN_VERSION, document_bytes, parse_origin_input
from .pdf_ingestion import extract_pdf_bytes
from .state import canonical_json_sha256


def verify_extraction(package):
    """Recheck the actual parser delivery, not a caller-supplied text hash."""
    for row in package.to_mapping()["fixtures"]:
        for name in ("document", "other_document"):
            item = row[name]
            text = extract_pdf_bytes(document_bytes(item)).text
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != item["extracted_text_sha256"]:
                raise PilotSeedError("invalid candidate A3a origin preparation")


def prepare_origin_input(cohort, *, member_index=0):
    """Only select POST *contexts* here, never synthesize a model POST output.

    Legitimate CREATE setup is administrative. The explicit index selects
    document provenance before execution, never an action/approval or policy.
    No label is delivered to the native preparer; the other member is solely
    a document/scenario negative. Default zero preserves DEC-068 bytes.
    All configuration remains candidate and requires independent review.
    """
    try:
        if type(member_index) is not int or member_index not in (0, 1):
            raise ValueError()
        cohort = _checked(cohort)
        seed = prepare_business_seed(cohort)
        values = seed.to_mapping()
        rows = []
        for generated in cohort.pairs:
            pair = generated.pair.to_mapping()
            truth = pair["truth"]
            if truth["expected_action"] != "POST_VENDOR_BILL":
                continue
            docs = []
            for kind, doc in zip(("benign", "adversarial"), generated.documents, strict=True):
                docs.append({**{name: pair["members"][kind][name] for name in (
                    "scenario_id", "document_sha256", "extracted_text_sha256")},
                    "pdf_base64": base64.b64encode(doc.pdf_bytes).decode("ascii")})
            day = date.fromisoformat(truth["invoice_date"])
            rows.append({"fixture_ref": pair["fixture_ref"], "pair_sha256": canonical_json_sha256(pair),
                "document_ref": truth["document_ref"],
                "invoice_date_min": day.replace(day=1).isoformat(),
                "invoice_date_max": day.replace(day=monthrange(day.year, day.month)[1]).isoformat(),
                "document": docs[member_index], "other_document": docs[1 - member_index]})
        package = parse_origin_input({"schema_version": ORIGIN_VERSION, "status": "CANDIDATE",
            "split": "pilot-v0", "synthetic_data": True, "fiscal_value": False,
            "seed_sha256": seed.sha256, "cohort_sha256": values["cohort_sha256"],
            "codebook_sha256": values["codebook_sha256"],
            "fixtures": sorted(rows, key=lambda row: row["fixture_ref"])})
        verify_extraction(package)
        return package
    except Exception:
        raise PilotSeedError("invalid candidate A3a origin preparation") from None

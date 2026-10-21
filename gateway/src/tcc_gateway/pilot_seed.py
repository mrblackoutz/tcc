"""DEC-067 compile verified candidate truth into administrative seed only."""

from .pilot_dataset import GeneratedPilotCohort, _checked
from .pilot_seed_contract import PilotSeedError, SEED_VERSION, parse_business_seed
from .state import canonical_json_sha256


def prepare_business_seed(cohort: GeneratedPilotCohort):
    """No payload/label/expected action is copied into the native seed."""
    try:
        checked = _checked(cohort)
        manifest = checked.to_manifest()
        rows = []
        for generated in checked.pairs:
            pair = generated.pair.to_mapping()
            truth = pair["truth"]
            rows.append({"fixture_ref": pair["fixture_ref"], "pair_sha256": canonical_json_sha256(pair),
                         **{name: truth[name] for name in (
                             "company_ref", "vendor_ref", "purchase_order_ref", "invoice_date", "currency",
                             "amount", "approved_bank_ref", "quantity_scale", "lines",
                         )}})
        return parse_business_seed({
            "schema_version": SEED_VERSION, "split": "pilot-v0", "status": "CANDIDATE",
            "synthetic_data": True, "fiscal_value": False,
            "cohort_sha256": canonical_json_sha256(manifest), "codebook_sha256": manifest["codebook_sha256"],
            "dataset_version": manifest["dataset_version"],
            "fixtures": sorted(rows, key=lambda row: row["fixture_ref"]),
        })
    except Exception:
        raise PilotSeedError("invalid candidate pilot business seed") from None

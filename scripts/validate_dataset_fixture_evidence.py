"""DEC-066 closed gate for ignored technical read-only fixture evidence.

Replays the existing fixture producer against every recorded JSON-2 read and
recomputes its evaluator handoff. Hashes identify mixed artifacts, not an
authenticated producer, independent review or a scientific dataset execution.
No HTTP headers, credential, exception text or traceback is emitted.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, DecimalException
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway" / "src"))
sys.path.insert(0, str(ROOT / "odoo" / "probes"))
sys.path.insert(0, str(ROOT / "scripts"))

from tcc_gateway.pdf_ingestion import extract_pdf_text
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256
from runner_dataset_fixture_gateway import evaluate_case, validate_inputs
from runner_observed_gateway import READ_MODELS
from validate_runner_observed_evidence import _hash, _shape, read_json


CASE_IDS = ("observed_create_benign", "observed_post_without_approval")
FILENAMES = (
    "dataset-fixture-inputs.json", "dataset-fixture-resolution.json",
    "dataset-fixture-confirmation.json",
)
DECLARATION_KEYS = frozenset({"git_base", "source_bundle_sha256", "configuration_sha256"})
FALSE_FLAGS = frozenset({
    "scientific_run", "human_review_complete", "public_executor_enabled",
    "external_provider_called", "approval_generated", "other_member_executed",
})
PROJECTION_MODELS = frozenset({
    "account.move", "account.move.line", "ap.security.draft.receipt", "ap.security.audit.event",
    "ap.security.approval.nonce", "ap.security.po.guard", "ap.security.vendor.guard",
    "ap.security.workflow.registration", "res.partner", "res.partner.bank", "purchase.order",
    "purchase.order.line", "account.lock_exception",
})
AUXILIARY_MODELS = frozenset({
    "account.payment", "account.partial.reconcile", "account.full.reconcile", "account.analytic.line",
    "mail.mail", "mail.notification", "mail.message", "ir.attachment",
})
PROJECTION_KEYS = PROJECTION_MODELS | {
    "attachments", "auxiliary_counts", "company_locks", "attachment_storage",
}
# Exact existing OperationalObservationProbe.projection fields. Closing this
# technical proof prevents an empty/field-truncated projection from self-equaling.
PROJECTION_FIELDS = {
    "account.move": "state move_type name posted_before ref invoice_date date partner_id partner_bank_id journal_id amount_total invoice_origin auto_post write_date",
    "account.move.line": "move_id purchase_line_id account_id quantity price_unit debit credit discount tax_ids write_date",
    "ap.security.draft.receipt": "executor_mode document_sha256 idempotency_key move_id command_sha256 action_sha256 receipt_payload write_date",
    "ap.security.audit.event": "status event_payload event_sha256 write_date",
    "ap.security.approval.nonce": "state command_sha256 action_sha256 nonce_sha256 consumed_at write_date",
    "ap.security.po.guard": "po_id revision write_date",
    "ap.security.vendor.guard": "vendor_id revision write_date",
    "ap.security.workflow.registration": "registration_payload registration_sha256 write_date",
    "res.partner": "ref active supplier_rank autopost_bills write_date",
    "res.partner.bank": "partner_id active acc_number allow_out_payment write_date",
    "purchase.order": "state partner_id currency_id amount_total invoice_status write_date",
    "purchase.order.line": "order_id product_qty qty_invoiced qty_to_invoice price_unit tax_ids discount write_date",
    "account.lock_exception": "user_id active state lock_date_field lock_date write_date",
    "attachments": "target model hash private storage_db mime write_date",
    "company_locks": "fiscalyear_lock_date hard_lock_date tax_lock_date sale_lock_date purchase_lock_date",
}
_MAX_CALLS = 100


def _require(condition):
    if not condition:
        raise ValueError("dataset fixture evidence invalid")


def _closed(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _same(first, second):
    # Python equality treats True == 1; the evidence contract does not.
    return canonical_json_bytes(first) == canonical_json_bytes(second)


def _ids(rows):
    _require(type(rows) is list)
    identities = []
    for row in rows:
        _require(type(row) is dict and type(row.get("id")) is int and row["id"] > 0)
        identities.append(row["id"])
    _require(identities == sorted(set(identities)))
    return set(identities)


def _relation(value):
    _require(type(value) is list and len(value) == 2 and type(value[0]) is int
             and value[0] > 0 and type(value[1]) is str)
    return value[0]


def _decimal(value):
    _require(type(value) in {int, float, str})
    try:
        number = Decimal(str(value))
    except DecimalException:
        raise ValueError("dataset fixture evidence invalid") from None
    _require(number.is_finite())
    return number


def _projection(value, case, ledger_lines):
    """Require the actual existing technical projection, never a bare PASS."""
    _closed(value, PROJECTION_KEYS)
    for model, fields in PROJECTION_FIELDS.items():
        _require(type(value[model]) is list)
        for row in value[model]:
            _closed(row, {"id", *fields.split()})
    identities = {model: _ids(value[model]) for model in PROJECTION_MODELS}
    binding = case["binding"]
    for model, expected in (
        ("res.partner", [binding["vendor_id"]]),
        ("res.partner.bank", binding["allowed_bank_ids"]),
        ("purchase.order", [binding["purchase_order_id"]]),
        ("purchase.order.line", binding["purchase_line_ids"]),
        ("ap.security.workflow.registration", [binding["registration_id"]]),
    ):
        _require(set(expected) <= identities[model])
    action = case["legitimate_action"]
    vendor = next(row for row in value["res.partner"] if row["id"] == binding["vendor_id"])
    _require(vendor["ref"] == action["vendor_ref"] and vendor["active"] is True)
    order = next(row for row in value["purchase.order"] if row["id"] == binding["purchase_order_id"])
    _require(order["state"] == "purchase" and _relation(order["partner_id"]) == binding["vendor_id"]
             and _decimal(order["amount_total"]) == _decimal(action["amount"]))
    banks = [row for row in value["res.partner.bank"] if row["acc_number"] == action["recipient_bank_ref"]]
    _require(len(banks) == 1)
    bank = banks[0]
    _require(bank["id"] in binding["allowed_bank_ids"] and bank["active"] is True
             and bank["allow_out_payment"] is True and _relation(bank["partner_id"]) == binding["vendor_id"])
    by_item = {line["item_code"]: line for line in action["lines"]}
    for expected in case["expected_lines"]:
        line = next(row for row in value["purchase.order.line"] if row["id"] == expected["purchase_line_id"])
        truth = by_item[expected["item_code"]]
        _require(_relation(line["order_id"]) == binding["purchase_order_id"]
                 and _decimal(line["product_qty"]) == _decimal(truth["quantity"])
                 and _decimal(line["price_unit"]) == _decimal(truth["unit_price"])
                 and _decimal(line["discount"]) == 0 and line["tax_ids"] == [])
        if case["target_move_id"] is None:
            _require(_decimal(line["qty_to_invoice"]) >= _decimal(truth["quantity"]))
    target = case["target_move_id"]
    if target is not None:
        _require(target in identities["account.move"])
        row = next(row for row in value["account.move"] if row["id"] == target)
        _require(row.get("state") == "draft" and row.get("move_type") == "in_invoice")
        _require((row["ref"], row["invoice_date"], row["invoice_origin"]) == (
            action["document_ref"], action["invoice_date"], action["purchase_order_ref"],
        ) and _relation(row["partner_id"]) == binding["vendor_id"]
            and _relation(row["partner_bank_id"]) == bank["id"]
            and _relation(row["journal_id"]) == binding["journal_id"]
            and _decimal(row["amount_total"]) == _decimal(action["amount"]))
        # Include every target line with a PO link, not just known line IDs.
        # Payable counterparts legitimately have no purchase_line_id. Product
        # identity is checked by the replayed resolver, since this historical
        # native projection deliberately does not contain product_id.
        target_lines = [line for line in value["account.move.line"]
                        if _relation(line["move_id"]) == target
                        and line["purchase_line_id"] is not False]
        expected_by_po = {line["purchase_line_id"]: by_item[line["item_code"]]
                          for line in case["expected_lines"]}
        observed_by_po = {}
        for line in target_lines:
            purchase_line_id = _relation(line["purchase_line_id"])
            _require(purchase_line_id in expected_by_po and purchase_line_id not in observed_by_po)
            observed_by_po[purchase_line_id] = line
            truth = expected_by_po[purchase_line_id]
            _require(_decimal(line["quantity"]) == _decimal(truth["quantity"])
                     and _decimal(line["price_unit"]) == _decimal(truth["unit_price"])
                     and _decimal(line["discount"]) == 0 and line["tax_ids"] == [])
        _require(set(observed_by_po) == set(expected_by_po))
        _require({line["id"] for line in target_lines} == {line["id"] for line in ledger_lines})
        for line in ledger_lines:
            purchase_line_id = _relation(line["purchase_line_id"])
            projected = observed_by_po[purchase_line_id]
            _require(_relation(line["move_id"]) == target and line["id"] == projected["id"]
                     and _decimal(line["quantity"]) == _decimal(projected["quantity"])
                     and _decimal(line["price_unit"]) == _decimal(projected["price_unit"])
                     and _decimal(line["discount"]) == 0 and line["tax_ids"] == [])
    _ids(value["attachments"])
    locks = value["company_locks"]
    _require(_ids(locks) == {binding["company_id"]} and len(locks) == 1)
    _closed(value["auxiliary_counts"], AUXILIARY_MODELS)
    for count in value["auxiliary_counts"].values():
        _require(type(count) is int and count >= 0)
    _require(value["auxiliary_counts"]["account.payment"] == 0
             and value["ap.security.approval.nonce"] == []
             and value["attachment_storage"] == "db")


class ReplayCaller:
    """Closed deterministic transport; records cannot add or hide calls."""

    def __init__(self, calls):
        _require(type(calls) is list and 1 <= len(calls) <= _MAX_CALLS)
        self.calls, self.index = calls, 0
        for call in calls:
            _closed(call, {"model", "method", "arguments", "result"})
            _require(type(call["model"]) is str and call["model"] in READ_MODELS
                     and call["method"] == "search_read")
            arguments = call["arguments"]
            _closed(arguments, {"domain", "fields", "limit", "order"})
            _require(type(arguments["domain"]) is list and type(arguments["fields"]) is list
                     and all(type(field) is str for field in arguments["fields"])
                     and type(arguments["limit"]) is int and 1 <= arguments["limit"] <= 100
                     and arguments["order"] == "id asc"
                     and type(call["result"]) is list)
            _require(len(call["result"]) <= arguments["limit"])
            for row in call["result"]:
                _closed(row, {"id", *arguments["fields"]})

    def call(self, model, method, *, arguments):
        _require(self.index < len(self.calls))
        call = self.calls[self.index]
        _require(_same([model, method, arguments], [call["model"], call["method"], call["arguments"]]))
        self.index += 1
        return deepcopy(call["result"])

    def finish(self):
        _require(self.index == len(self.calls))


def validate_bundle(records, documents, *, git_base, source_bundle_sha256, input_sha256):
    """Recompute all joins; inputs and the private read ledger remain unchanged."""
    _hash(git_base, commit=True)
    _hash(source_bundle_sha256)
    _hash(input_sha256)
    _closed(records, FILENAMES)
    _closed(documents, CASE_IDS)
    _shape(records)
    inputs, resolution, confirmation = (records[name] for name in FILENAMES)
    validate_inputs(inputs, SimpleNamespace(git_base=git_base, source_bundle_sha256=source_bundle_sha256))
    _require(inputs["git_base"] == git_base and inputs["source_bundle_sha256"] == source_bundle_sha256)
    _require(type(inputs["reader_user_id"]) is int and inputs["reader_user_id"] > 1
             and "SEM VALOR FISCAL" in inputs["company_name"])
    _require(all(inputs["reader_user_id"] != case["binding"]["executor_user_id"]
                 for case in inputs["cases"]))
    declaration = {name: inputs[name] for name in DECLARATION_KEYS}
    _hash(declaration["configuration_sha256"])
    for value, schema, additional in (
        (resolution, "dataset-fixture-resolution/v1", {"input_sha256", *FALSE_FLAGS}),
        (confirmation, "dataset-fixture-native-confirmation/v1", {"reader_readonly_acl_verified"}),
    ):
        _closed(value, {"schema_version", "status", "cases", *DECLARATION_KEYS, *additional})
        _require(value["schema_version"] == schema and value["status"] == "PASS")
        _require(all(value[name] == declaration[name] for name in DECLARATION_KEYS))
        _require(type(value["cases"]) is list and len(value["cases"]) == 2
                 and tuple(case.get("name") for case in value["cases"] if type(case) is dict) == CASE_IDS)
    _require(resolution["input_sha256"] == input_sha256)
    _require(all(resolution[name] is False for name in FALSE_FLAGS)
             and confirmation["reader_readonly_acl_verified"] is True)
    request_count = 0
    for case, resolved, confirmed in zip(inputs["cases"], resolution["cases"], confirmation["cases"], strict=True):
        _closed(resolved, {"name", "result", "calls"})
        _closed(confirmed, {"name", "projection"})
        name = case["name"]
        document = documents[name]
        _require(document.document_sha256 == case["workflow"]["document_sha256"])
        replay = ReplayCaller(resolved["calls"])
        result = evaluate_case(case, document, replay)
        replay.finish()
        _require(_same(result, resolved["result"]))
        line_calls = [call for call in resolved["calls"] if call["model"] == "account.move.line"]
        _require(len(line_calls) == (0 if case["target_move_id"] is None else 1))
        ledger_lines = [] if not line_calls else line_calls[0]["result"]
        before, after, fresh = case["projection_before"], case["projection_after"], confirmed["projection"]
        for projection in (before, after, fresh):
            _projection(projection, case, ledger_lines)
        _require(_same(before, after) and _same(before, fresh))
        # Equality is recomputed over the content, not an asserted hash/check.
        _require(canonical_json_sha256(before) == canonical_json_sha256(after)
                 == canonical_json_sha256(fresh))
        request_count += len(resolved["calls"])
    return {"case_count": 2, "native_json2_request_count": request_count,
            "configuration_sha256": declaration["configuration_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate private DEC-066 read-only fixture evidence")
    for name in ("artifacts", "git-base", "source-bundle-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    result = {"schema_version": "dataset-fixture-validation/v1", "status": "FAIL", "case_count": 0,
              "native_json2_request_count": 0, "scientific_run": False,
              "human_review_complete": False, "public_executor_enabled": False}
    output = None
    try:
        artifacts = Path(args.artifacts).resolve(strict=True)
        allowed = (ROOT / ".runtime" / "runner-native").resolve()
        _require(artifacts.is_dir() and artifacts.is_relative_to(allowed) and artifacts.name == "artifacts")
        candidate_output = Path(args.output).resolve()
        _require(candidate_output.name == "dataset-fixture-validation.json"
                 and candidate_output.parent in {artifacts, artifacts.parent})
        output = candidate_output
        records, hashes, documents = {}, {}, {}
        for filename in FILENAMES:
            path = (artifacts / filename).resolve(strict=True)
            _require(path.parent == artifacts and path.is_file())
            records[filename], hashes[filename] = read_json(path)
        for name in CASE_IDS:
            path = (artifacts / (name + ".pdf")).resolve(strict=True)
            _require(path.parent == artifacts and path.is_file())
            documents[name] = extract_pdf_text(path)
        result.update(validate_bundle(records, documents, git_base=args.git_base,
            source_bundle_sha256=args.source_bundle_sha256, input_sha256=hashes[FILENAMES[0]]))
        result.update(status="PASS", git_base=args.git_base, source_bundle_sha256=args.source_bundle_sha256,
                      artifact_sha256=hashes)
    except Exception:
        result["status"] = "FAIL"
    encoded = canonical_json_bytes(result).decode("utf-8") + "\n"
    if output is not None:
        try:
            output.write_text(encoded, encoding="utf-8")
        except OSError:
            result["status"] = "FAIL"
            encoded = canonical_json_bytes(result).decode("utf-8") + "\n"
    print(encoded, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""DEC-055 offline gates for the native collector; not an Odoo test count."""

import ast
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "odoo/probes/company_capture_native.py"
sys.path.insert(0, str(ROOT / "gateway/src"))
SPEC = importlib.util.spec_from_file_location("tcc_company_capture_native", SOURCE)
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


@pytest.mark.parametrize("value,expected", [
    (0, "0"), (0.0, "0"), (-0.0, "0"), (1, "1"), (1.50, "1.5"),
    (Decimal("12.50000"), "12.5"), (Decimal("0.000001"), "0.000001"),
    ("-2.5", "-2.5"), ("1e-8", "0.00000001"),
])
def test_decimal_projection_preserves_finite_values_without_quantity_rounding(value, expected):
    assert NATIVE.decimal_text(value) == expected


@pytest.mark.parametrize("value", [True, False, None, [], {}, float("inf"), float("nan"),
                                  Decimal("-Infinity"), "NaN", "not-decimal"])
def test_decimal_projection_rejects_wrong_types_and_nonfinite_values(value):
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE.decimal_text(value)


@pytest.mark.parametrize("value,expected", [(1, "1.00"), (125.5, "125.50"), (0, "0.00"),
                                           (Decimal("-2.50"), "-2.50")])
def test_monetary_projection_exactly_matches_two_decimal_endpoint(value, expected):
    assert NATIVE.decimal_text(value, money=True) == expected


def test_money_does_not_round_away_an_unrepresentable_native_amount():
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE.decimal_text(Decimal("125.501"), money=True)


def test_json_relation_mapping_changes_only_explicit_known_identity_fields():
    observed = []

    def visit(model, identity):
        observed.append((model, identity))
        return identity + 100

    source = {"subject": {"company_id": 2}, "receipt": {"move_id": 4, "receipt_id": 5},
              "revision": 2, "quantity": 125,
              "scenario_id": "TCC-1", "approval": None, "other": [1, 2]}
    result = NATIVE._json_relations(source, visit, contract="event_payload")
    assert result == {"subject": {"company_id": 102}, "receipt": {"move_id": 104, "receipt_id": 105},
                      "revision": 2, "quantity": 125,
                      "scenario_id": "TCC-1", "approval": None, "other": [1, 2]}
    assert source["subject"]["company_id"] == 2
    assert observed == [("res.company", 2), ("account.move", 4),
                        ("ap.security.draft.receipt", 5)]


def test_json_relations_accept_allowlisted_workflow_list_paths_only():
    value = {"workflow": {"purchase_line_ids": [9, 7]}, "quantity_scale": 2}
    assert NATIVE._json_relations(value, lambda _model, identity: identity + 100,
                                   contract="registration_payload") == {
        "workflow": {"purchase_line_ids": [107, 109]}, "quantity_scale": 2}
    for other in ({"evidence": {"company_id": 123}}, {"company_id": 123}):
        with pytest.raises(NATIVE.CompanyCaptureError):
            NATIVE._json_relations(other, lambda _model, identity: identity,
                                     contract="event_payload")


@pytest.mark.parametrize("source", [
    {"company_id": True}, {"company_id": 0}, {"company_id": -1}, {"company_id": "2"},
    {"purchase_line_ids": [False]}, {"purchase_line_ids": (1, 2)},
    {"other": 1.5}, {1: "not-string-key"},
])
def test_json_relation_mapping_rejects_invalid_identities_without_repair(source):
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE._json_relations(source, lambda _model, identity: identity,
                                 contract="registration_payload")


def test_json_relation_recursion_is_bounded():
    source = None
    for _ in range(22):
        source = {"child": source}
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE._json_relations(source, lambda _model, identity: identity,
                                 contract="event_payload")


def test_identity_maps_are_model_specific_dense_ordinals_not_native_ids():
    maps = NATIVE._ordinal_maps({"account.move": {91, 14}, "res.partner": {91}})
    assert maps == {"account.move": {14: 1, 91: 2}, "res.partner": {91: 1}}
    assert NATIVE._ref(maps, "account.move", 91) == 2
    assert NATIVE._ref(maps, "res.partner", 91) == 1
    assert NATIVE._ref(maps, "res.partner", False) is None
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE._ref(maps, "account.move", 99)


def test_native_values_have_exact_types_dates_and_nulls():
    assert NATIVE._value("active", True) is True
    assert NATIVE._value("revision", 3) == 3
    assert NATIVE._value("ref", False) is None
    assert NATIVE._value("invoice_date", date(2026, 10, 16)) == "2026-10-16"
    assert NATIVE._value("verified_at", datetime(2026, 10, 16, 12)) == "2026-10-16T12:00:00Z"
    assert NATIVE._value("verified_at", datetime(2026, 10, 16, 12, tzinfo=timezone.utc)) == "2026-10-16T12:00:00Z"
    for name, value in (("active", 1), ("revision", False), ("name", ["not-text"])):
        with pytest.raises(NATIVE.CompanyCaptureError):
            NATIVE._value(name, value)


@pytest.mark.parametrize("value,expected", [
    (False, None), (None, None), ("2026-10-16 12:30:45", "2026-10-16T12:30:45Z"),
    (datetime(2026, 10, 16, 12, 30, 45), "2026-10-16T12:30:45Z"),
])
def test_odoo_read_datetime_format_is_explicitly_exported_as_utc(value, expected):
    assert NATIVE._datetime_value(value) == expected


@pytest.mark.parametrize("value", [123, [], True, "bad-date", "2026-10-16T12:30:00+03:00"])
def test_invalid_native_datetime_is_rejected_without_value_in_diagnostic(value):
    with pytest.raises(NATIVE.CompanyCaptureError, match="^native company capture rejected$"):
        NATIVE._datetime_value(value)


def test_filestore_captures_orphans_and_nested_files_sorted_by_relative_path(tmp_path):
    (tmp_path / "bb").mkdir()
    (tmp_path / "bb" / "linked").write_bytes(b"linked bytes")
    (tmp_path / "orphan").write_bytes(b"orphan bytes")
    result = NATIVE.filestore_projection(tmp_path)
    assert result == [
        {"path": "bb/linked", "size": 12, "sha256": hashlib.sha256(b"linked bytes").hexdigest()},
        {"path": "orphan", "size": 12, "sha256": hashlib.sha256(b"orphan bytes").hexdigest()},
    ]
    assert NATIVE.filestore_projection(tmp_path) == result
    (tmp_path / "orphan").write_bytes(b"changed bytes")
    assert NATIVE.filestore_projection(tmp_path) != result


def test_filestore_does_not_accept_missing_root(tmp_path):
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE.filestore_projection(tmp_path / "missing")


def test_filestore_rejects_symlink_without_following_outside_root(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    root = tmp_path / "store"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("host does not permit unprivileged symlink fixture")
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE.filestore_projection(root)


def test_file_and_file_count_limits_fail_instead_of_truncating(tmp_path, monkeypatch):
    (tmp_path / "one").write_bytes(b"bytes")
    monkeypatch.setattr(NATIVE, "MAX_FILE_BYTES", 4)
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE.filestore_projection(tmp_path)
    monkeypatch.setattr(NATIVE, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(NATIVE, "MAX_FILES", 0)
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE.filestore_projection(tmp_path)


def test_attachment_checksum_is_checked_against_actual_file_bytes(tmp_path):
    path = tmp_path / "payload"
    path.write_bytes(b"fixture bytes")
    good = hashlib.sha1(b"fixture bytes", usedforsecurity=False).hexdigest()
    assert NATIVE._file_digest(path, tmp_path, expected_sha1=good)["sha256"] == hashlib.sha256(b"fixture bytes").hexdigest()
    with pytest.raises(NATIVE.CompanyCaptureError):
        NATIVE._file_digest(path, tmp_path, expected_sha1="0" * 40)


def test_postgres_sequence_order_and_physical_oids_do_not_define_reset_identity():
    maps = {"ir.sequence": {41: 1}, "ir.sequence.date_range": {81: 1}}
    source = [("res_partner_id_seq", 1), ("ir_sequence_041_081", 2),
              ("account_move_id_seq", 1), ("ir_sequence_099", 1)]
    expected = [("account_move_id_seq", "account_move_id_seq", 1),
                ("ir.sequence:1/ir.sequence.date_range:1", "ir_sequence_041_081", 2),
                ("res_partner_id_seq", "res_partner_id_seq", 1)]
    assert NATIVE._sequence_metadata(source, maps) == expected
    assert NATIVE._sequence_metadata(list(reversed(source)), maps) == expected
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_postgres_sequences")
    assert "c.oid" not in ast.unparse(function)


def test_unlinked_scope_cannot_be_filtered_by_proposal_or_document_reference():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    roots = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_roots")
    assert [arg.arg for arg in roots.args.args] == ["env", "company_id"]
    text = ast.unparse(roots)
    for name in ("account.move", "account.payment", "purchase.order", "ap.security.draft.receipt",
                 "ap.security.audit.event", "ap.security.approval.nonce", "ap.security.po.guard",
                 "ap.security.vendor.guard", "ap.security.workflow.registration"):
        assert repr(name) in text
    assert "move_type" not in text and "document_ref" not in text and "scenario_id" not in text


def test_native_collector_cannot_mutate_or_advance_sequences():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    forbidden = {"create", "write", "unlink", "action_post", "commit", "rollback", "_next", "next_by_id",
                 "next_by_code", "_select_nextval", "_update_nogap", "set_test_mode", "patch"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in forbidden for node in ast.walk(tree))
    statements = [node.value.lower() for node in ast.walk(tree) if isinstance(node, ast.Constant)
                  and type(node.value) is str and ("select " in node.value.lower() or "show " in node.value.lower())]
    assert statements and all("nextval(" not in statement and "setval(" not in statement for statement in statements)
    assert "show transaction_read_only" in statements


def test_source_fields_are_derived_from_single_shared_closed_schema():
    assert "content_sha256" not in NATIVE._source_fields("ir.attachment")
    assert "res_id" in NATIVE._source_fields("ir.attachment")
    assert "res_id" in NATIVE._source_fields("mail.message")
    assert "subtype_id" in NATIVE._source_fields("mail.message")
    assert "subtype_ref" not in NATIVE._source_fields("mail.message")
    assert "event_payload" in NATIVE._source_fields("ap.security.audit.event")


def test_only_known_nonsecret_configuration_parameter_is_selected():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    roots = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_roots")
    text = ast.unparse(roots)
    assert "'account.lock_exception'" in text
    assert "('key', '=', 'ir_attachment.location')" in text
    assert "ids['ir.config_parameter'].update" in text


def test_no_duplicated_oracle_rows_and_reset_hash_excludes_binding_and_native_ids():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "collect")
    text = ast.unparse(function)
    assert "oracle_rows" not in text
    assert "canonical_json_sha256({'records': records, 'filestore': files_after})" in text
    assert "CaptureBinding.from_mapping(binding)" in text
    assert "files_before == files_after" in text

"""DEC-073 pure clone/CLI tests; native integration requires the Docker proof."""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "odoo/probes/pilot_reset_native.py"
SPEC = importlib.util.spec_from_file_location("pilot_reset_native_contract_test", ENTRY)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def case():
    proof = {"schema_version": "pilot-materialization-reset-inputs/v1", "seed_sha256": "a" * 64,
             "catalog_sha256": "b" * 64, "origin_input_sha256s": ["c" * 64, "d" * 64],
             "cohort_sha256": "e" * 64, "codebook_sha256": "f" * 64}
    original = {"database": "tcc_runner_0123456789ab", "git_base": "1" * 40,
                "source_bundle_sha256": "2" * 64, "company_id": 2, "company_name": "TCC PROTEÇÃO",
                "configuration_sha256": "3" * 64, "cases": [{"registration_id": 17}]}
    rewritten = dict(original, database="tcc_runner_1123456789ab")
    binding = {"schema_version": "pilot-reset-clone-binding/v1", "source_database": original["database"],
               "target_database": rewritten["database"], "original_manifest_sha256": native._sha(original),
               "rewritten_manifest_sha256": native._sha(rewritten), "snapshot_manifest_sha256": "4" * 64,
               "seed_sha256": proof["seed_sha256"], "catalog_sha256": proof["catalog_sha256"],
               "origin_input_sha256": proof["origin_input_sha256s"][0], "fixture_ref": "FIX-001"}
    arguments = {"database": rewritten["database"], "git_base": original["git_base"],
                 "source_bundle_sha256": original["source_bundle_sha256"],
                 "snapshot_sha256": "4" * 64, "origin_sha256": "c" * 64, "fixture_ref": "FIX-001"}
    return binding, original, rewritten, proof, arguments


def test_exact_clone_remaps_only_database_and_preserves_unicode_hashes():
    binding, original, rewritten, proof, arguments = case()
    originals = deepcopy((binding, original, rewritten, proof, arguments))
    assert native._check_clone(binding, original, rewritten, proof, **arguments) is binding
    assert (binding, original, rewritten, proof, arguments) == originals
    assert native._sha(original) == hashlib.sha256(json.dumps(original, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    assert b"\\u00c7" in native._canonical(original)


@pytest.mark.parametrize("field", sorted(native._CLONE_KEYS))
def test_all_clone_binding_fields_closed_and_required(field):
    binding, original, rewritten, proof, arguments = case()
    del binding[field]
    with pytest.raises(ValueError):
        native._check_clone(binding, original, rewritten, proof, **arguments)


@pytest.mark.parametrize("field", sorted(native._CLONE_KEYS - {"schema_version"}))
def test_changed_clone_binding_rejected(field):
    binding, original, rewritten, proof, arguments = case()
    binding[field] = "untrusted"
    with pytest.raises(ValueError):
        native._check_clone(binding, original, rewritten, proof, **arguments)


@pytest.mark.parametrize("field", ["database", "git_base", "source_bundle_sha256", "snapshot_sha256",
                                  "origin_sha256", "fixture_ref"])
def test_mismatched_requested_identity_input_or_fixture_rejected(field):
    binding, original, rewritten, proof, arguments = case()
    arguments[field] = "other"
    with pytest.raises(ValueError):
        native._check_clone(binding, original, rewritten, proof, **arguments)


@pytest.mark.parametrize("field,value", [("company_id", 9), ("company_name", "TCC OTHER"),
    ("cases", [{"registration_id": 99}]), ("configuration_sha256", "9" * 64),
    ("git_base", "9" * 40), ("source_bundle_sha256", "9" * 64)])
def test_rehashed_rewritten_manifest_still_cannot_change_trusted_fields(field, value):
    binding, original, rewritten, proof, arguments = case()
    rewritten[field] = value
    binding["rewritten_manifest_sha256"] = native._sha(rewritten)
    with pytest.raises(ValueError):
        native._check_clone(binding, original, rewritten, proof, **arguments)


def test_extra_clone_key_and_identical_source_target_rejected():
    binding, original, rewritten, proof, arguments = case()
    binding["approval"] = True
    with pytest.raises(ValueError):
        native._check_clone(binding, original, rewritten, proof, **arguments)
    del binding["approval"]
    binding["source_database"] = binding["target_database"]
    with pytest.raises(ValueError):
        native._check_clone(binding, original, rewritten, proof, **arguments)


@pytest.mark.parametrize("field", sorted(native._INPUT_KEYS))
def test_proof_inputs_are_closed_and_all_required(field):
    proof = case()[3]
    assert native._proof(proof) is proof
    del proof[field]
    with pytest.raises(ValueError):
        native._proof(proof)


@pytest.mark.parametrize("origins", [[], ["c" * 64], ["c" * 64] * 2,
    ["c" * 64, "d" * 64, "e" * 64], ["c" * 64, "bad"], ["c" * 64, 2]])
def test_two_distinct_origin_inputs_required(origins):
    proof = case()[3]
    proof["origin_input_sha256s"] = origins
    with pytest.raises(ValueError):
        native._proof(proof)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'{}{}', b''])
def test_local_json_duplicate_nonfinite_invalid_or_nonobject_rejected(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        native._read(path)


def test_local_json_roundtrip_and_limit(tmp_path):
    path = tmp_path / "input.json"
    native._write(path, {"synthetic": True})
    assert native._read(path) == {"synthetic": True}
    with pytest.raises(ValueError):
        native._bytes(path, 2)


@pytest.mark.parametrize("change", ["database", "config", "artifacts", "secret-directory", "git-base",
                                   "source-bundle-sha256"])
def test_bad_configuration_rejected_before_odoo_import(monkeypatch, change):
    arguments = {"database": "tcc_runner_0123456789ab", "git-base": "a" * 40,
                 "source-bundle-sha256": "b" * 64, "config": "/etc/odoo/runner.conf",
                 "artifacts": "/mnt/runner-artifacts", "secret-directory": "/run/runner-secrets"}
    arguments[change] = "invalid"
    argv = [str(ENTRY), "capture"]
    for key, value in arguments.items():
        argv.extend(["--" + key, value])
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="PILOT_RESET_INVALID_CONFIGURATION"):
        native.main()


@pytest.mark.parametrize("mode,extra", [("materialize", []), ("prepare", ["--fixture-ref", "FIX-001"]),
    ("capture", ["--fixture-ref", "FIX-001"]), ("prepare", ["--capture-label", "after"])])
def test_selection_and_capture_flags_cannot_change_other_modes(monkeypatch, mode, extra):
    monkeypatch.setattr(sys, "argv", [str(ENTRY), mode, "--database", "tcc_runner_0123456789ab",
        "--git-base", "a" * 40, "--source-bundle-sha256", "b" * 64, *extra])
    with pytest.raises(SystemExit, match="PILOT_RESET_INVALID_CONFIGURATION"):
        native.main()


def functions():
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    return {node.name: ast.unparse(node) for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_capture_uses_existing_collector_in_new_readonly_cursor_without_commit():
    text = functions()["capture"]
    assert "company_capture_native import collect" in text
    assert text.index("SET TRANSACTION READ ONLY") < text.index("api.Environment") < text.index("collect(")
    assert "args.capture_label == 'baseline'" in text and "capture-label" not in text
    assert ".commit(" not in text and ".unlink(" not in text


def test_preparation_reuses_seed_alternatives_and_real_filestore_sentinel():
    text = functions()["prepare"]
    assert "runner_observed_fixture import prepare" in text
    assert "runner_pilot_seed_native import run" in text and "runner_pilot_alternatives_native import run" in text
    assert "dataset_fixture_mode=True" in text
    assert text.index("prepare_observed(") < text.index("prepare_seed(") < text.index("prepare_alternatives(")
    assert "'ir_attachment.location', 'file'" in text and "'ir_attachment.location', 'db'" in text
    assert "attachment.store_fname" in text and "tcc-orphan-proof" in text and "open('xb')" in text
    assert "baseline-observed-manifest.json" in text and ".read_bytes()" in text


def test_validation_binds_actual_snapshot_and_origin_package_and_fixed_inputs():
    text = functions()["_validated"]
    assert "baseline/snapshot.json" in text and "hashlib.sha256(_bytes(" in text
    assert "PilotA3aOriginInput" in text and "package.sha256" in text
    assert "pilot-reset-binding.json" in text and "capture-binding.json" in text
    assert "'seed_sha256', 'cohort_sha256', 'codebook_sha256'" in text


def test_materialization_only_delegates_single_existing_private_create():
    text = functions()["materialize"]
    assert "runner_pilot_a3a_origin_native import run" in text
    assert "run(native, fixture_ref=args.fixture_ref)" in text
    assert text.index("_validated(args)") < text.index("run(native,")
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    prohibited = {"unlink", "button_cancel", "action_post", "issue_approval_fixture", "post_registered_bill_audited"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in prohibited for node in ast.walk(tree))
    sql_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"]
    assert len(sql_calls) == 1 and ast.literal_eval(sql_calls[0].args[0]) == "SET TRANSACTION READ ONLY"


def test_diagnostics_exclude_raw_exception_and_payload():
    text = functions()["main"]
    assert "str(error)" not in text and "repr(error)" not in text
    assert "source_line" in text and "source_file" in text and "category" in text
    assert "logging.disable(logging.CRITICAL)" in text

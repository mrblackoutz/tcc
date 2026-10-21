# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-073 adapter for existing preparation/capture, never an experimental run.

Only the disposable host harness restores databases and filestores. This native
adapter verifies the declared clone remapping before existing private CREATE.
Raw artifacts remain local; errors expose only finite source/type metadata.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import re
import traceback
from types import SimpleNamespace


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DB = re.compile(r"tcc_runner_[0-9a-f]{12}\Z")
_INPUT_KEYS = {"schema_version", "seed_sha256", "catalog_sha256", "origin_input_sha256s",
               "cohort_sha256", "codebook_sha256"}
_CLONE_KEYS = {"schema_version", "source_database", "target_database", "original_manifest_sha256",
               "rewritten_manifest_sha256", "snapshot_manifest_sha256", "seed_sha256", "catalog_sha256",
               "origin_input_sha256", "fixture_ref"}


def _require(value):
    if not value:
        raise ValueError("PILOT_RESET_NATIVE_INVALID")


def _canonical(value):
    # Host harness canonicalization uses ASCII escaping. Do not replace this
    # with c111_transactions.canonical, whose Unicode encoding differs.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bytes(path, limit):
    _require(path.is_file() and not path.is_symlink())
    info = path.stat()
    _require(info.st_nlink == 1 and 0 < info.st_size <= limit)
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    _require(len(raw) == info.st_size and len(raw) <= limit)
    return raw


def _read(path):
    def pairs(items):
        value = {}
        for key, child in items:
            _require(key not in value)
            value[key] = child
        return value

    def constant(_value):
        _require(False)

    value = json.loads(_bytes(path, 8_388_608), object_pairs_hook=pairs, parse_constant=constant)
    _require(type(value) is dict)
    nodes = 0

    def bounded(item, depth):
        nonlocal nodes
        nodes += 1
        _require(depth <= 24 and nodes <= 200_000)
        if type(item) is dict:
            for child in item.values():
                bounded(child, depth + 1)
        elif type(item) is list:
            for child in item:
                bounded(child, depth + 1)

    bounded(value, 0)
    return value


def _write(path, value):
    path.write_bytes(_canonical(value) + b"\n")


def _proof(value):
    _require(type(value) is dict and set(value) == _INPUT_KEYS
             and value["schema_version"] == "pilot-materialization-reset-inputs/v1")
    for name in _INPUT_KEYS - {"schema_version", "origin_input_sha256s"}:
        _require(type(value[name]) is str and _SHA.fullmatch(value[name]))
    origins = value["origin_input_sha256s"]
    _require(type(origins) is list and len(origins) == 2
             and all(type(item) is str and _SHA.fullmatch(item) for item in origins)
             and len(set(origins)) == 2)
    return value


def _check_clone(binding, original, rewritten, proof, *, database, git_base,
                 source_bundle_sha256, snapshot_sha256, origin_sha256, fixture_ref=None):
    """Pure closed remapping check; no values from LLM output or document text."""
    _require(type(binding) is dict and set(binding) == _CLONE_KEYS
             and binding["schema_version"] == "pilot-reset-clone-binding/v1")
    for name in ("source_database", "target_database"):
        _require(type(binding[name]) is str and _DB.fullmatch(binding[name]))
    _require(binding["source_database"] != binding["target_database"] == database)
    for name in _CLONE_KEYS - {"schema_version", "source_database", "target_database", "fixture_ref"}:
        _require(type(binding[name]) is str and _SHA.fullmatch(binding[name]))
    _require(type(binding["fixture_ref"]) is str and
             re.fullmatch(r"[A-Z0-9][A-Z0-9._ /-]{0,95}", binding["fixture_ref"]))
    _require(fixture_ref is None or type(fixture_ref) is str and fixture_ref == binding["fixture_ref"])
    _require(type(original) is dict and type(rewritten) is dict
             and original["database"] == binding["source_database"]
             and rewritten["database"] == binding["target_database"])
    expected = deepcopy(original)
    expected["database"] = database
    _require(rewritten == expected and original["git_base"] == git_base
             and original["source_bundle_sha256"] == source_bundle_sha256
             and rewritten["company_id"] == original["company_id"])
    _require(binding["original_manifest_sha256"] == _sha(original)
             and binding["rewritten_manifest_sha256"] == _sha(rewritten)
             and binding["snapshot_manifest_sha256"] == snapshot_sha256
             and binding["seed_sha256"] == proof["seed_sha256"]
             and binding["catalog_sha256"] == proof["catalog_sha256"]
             and binding["origin_input_sha256"] == origin_sha256
             and origin_sha256 in proof["origin_input_sha256s"])
    return binding


def _inputs(args):
    from tcc_gateway.pilot_seed_contract import (
        MAX_SEED_BYTES, MAX_ALTERNATIVES_BYTES, PilotBusinessSeed, PilotAlternativeCatalog,
        validate_alternatives,
    )
    root = Path(args.artifacts)
    proof = _proof(_read(root / "proof-inputs.json"))
    seed = PilotBusinessSeed(_bytes(root / "pilot-business-seed.json", MAX_SEED_BYTES))
    catalog = PilotAlternativeCatalog(_bytes(root / "pilot-alternatives.json", MAX_ALTERNATIVES_BYTES))
    value = validate_alternatives(seed, catalog)
    _require(seed.sha256 == proof["seed_sha256"] and catalog.sha256 == proof["catalog_sha256"]
             and all(value[name] == proof[name] for name in ("cohort_sha256", "codebook_sha256")))
    return root, proof


def _capture_binding(original, proof, args):
    return {"company_id": original["company_id"], "company_name": original["company_name"],
            "fixture_manifest_sha256": _sha(original), "code_commit": args.git_base,
            "code_sha256": args.source_bundle_sha256, "configuration_sha256": _sha(proof)}


def _validated(args, *, baseline=False):
    root, proof = _inputs(args)
    original = _read(root / "baseline-observed-manifest.json")
    rewritten = _read(root / "observed-manifest.json")
    _require(original["git_base"] == args.git_base
             and original["source_bundle_sha256"] == args.source_bundle_sha256)
    capture_binding = _capture_binding(original, proof, args)
    _require(_read(root / "capture-binding.json") == capture_binding)
    if baseline:
        _require(not (root / "pilot-reset-binding.json").exists()
                 and original == rewritten and original["database"] == args.database)
    else:
        from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES, PilotA3aOriginInput
        package = PilotA3aOriginInput(_bytes(root / "pilot-a3a-origin.json", MAX_ORIGIN_BYTES))
        package_value = package.to_mapping()
        _require(all(package_value[name] == proof[name] for name in
                     ("seed_sha256", "cohort_sha256", "codebook_sha256")))
        snapshot_sha = hashlib.sha256(_bytes(root / "baseline/snapshot.json", 4_194_304)).hexdigest()
        binding = _check_clone(_read(root / "pilot-reset-binding.json"), original, rewritten, proof,
            database=args.database, git_base=args.git_base, source_bundle_sha256=args.source_bundle_sha256,
            snapshot_sha256=snapshot_sha, origin_sha256=package.sha256, fixture_ref=args.fixture_ref)
        _require(sum(row["fixture_ref"] == binding["fixture_ref"] for row in package_value["fixtures"]) == 1)
    return root, proof, rewritten, capture_binding


def prepare(registry, args):
    from runner_observed_fixture import prepare as prepare_observed
    from runner_pilot_seed_native import run as prepare_seed
    from runner_pilot_alternatives_native import run as prepare_alternatives
    from odoo import api, SUPERUSER_ID
    root, proof = _inputs(args)
    _require(not (root / "pilot-reset-binding.json").exists())
    native = SimpleNamespace(**vars(args), dataset_fixture_mode=True,
                             pilot_seed_sha256=proof["seed_sha256"],
                             pilot_alternatives_sha256=proof["catalog_sha256"])
    prepare_observed(registry, native)
    native.mode = "pilot-business-seed"
    prepare_seed(native)
    native.mode = "pilot-alternatives"
    prepare_alternatives(native)
    result = _read(root / "pilot-alternatives-result.json")
    _require(result["technical_resolution_complete"] is True
             and result["purchase_order_line_gap_count"] == 0)
    original = _read(root / "observed-manifest.json")
    _require(original["database"] == args.database and original["git_base"] == args.git_base
             and original["source_bundle_sha256"] == args.source_bundle_sha256)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID,
                              {"allowed_company_ids": [original["company_id"]]}, su=True)
        mode = getattr(registry, "in_test_mode", None)
        _require(type(cr).__name__ == "Cursor" and not getattr(registry, "test_cr", None)
                 and not (mode() if callable(mode) else mode))
        env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        attachment = env["ir.attachment"].create({
            "name": "TCC PILOT RESET - SEM VALOR FISCAL.txt", "type": "binary",
            "raw": b"TCC SYNTHETIC PILOT RESET WITHOUT FISCAL VALUE\n", "mimetype": "text/plain",
            "company_id": original["company_id"], "res_model": "res.company",
            "res_id": original["company_id"],
        })
        _require(bool(attachment.store_fname) and bool(attachment.raw))
        orphan = Path(attachment._filestore()) / "tcc-orphan-proof"
        with orphan.open("xb") as output:
            output.write(b"TCC ORPHAN SYNTHETIC FILE WITHOUT FISCAL VALUE\n")
        env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        cr.commit()
    (root / "baseline-observed-manifest.json").write_bytes((root / "observed-manifest.json").read_bytes())
    _write(root / "capture-binding.json", _capture_binding(original, proof, args))
    _validated(args, baseline=True)


def capture(registry, args):
    import odoo
    from odoo import api, SUPERUSER_ID
    from company_capture_native import collect
    root, _proof_value, _manifest, binding = _validated(args, baseline=args.capture_label == "baseline")
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        env = api.Environment(cr, SUPERUSER_ID, {"allowed_company_ids": [binding["company_id"]]}, su=True)
        filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
        value = collect(env, binding, filestore)
    _write(root / (args.capture_label + ".capture.json"), value)


def materialize(registry, args):
    from runner_pilot_a3a_origin_native import run
    root, proof, _manifest, _binding = _validated(args)
    binding = _read(root / "pilot-reset-binding.json")
    native = SimpleNamespace(**vars(args), dataset_fixture_mode=True,
                             pilot_seed_sha256=proof["seed_sha256"],
                             pilot_a3a_origin_sha256=binding["origin_input_sha256"])
    native.mode = "pilot-a3a-origins"
    contexts = run(native, fixture_ref=args.fixture_ref)
    if args.with_approval_binding:
        from pilot_approval_native import run as prepare_approval
        prepare_approval(args, registry, contexts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "capture", "materialize"))
    parser.add_argument("--database", required=True)
    parser.add_argument("--git-base", required=True)
    parser.add_argument("--source-bundle-sha256", required=True)
    parser.add_argument("--config", default="/etc/odoo/runner.conf")
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    parser.add_argument("--secret-directory", default="/run/runner-secrets")
    parser.add_argument("--fixture-ref")
    parser.add_argument("--with-approval-binding", action="store_true")
    parser.add_argument("--capture-label", choices=("baseline", "before", "after", "restored"), default="baseline")
    args = parser.parse_args()
    if (not _DB.fullmatch(args.database) or not re.fullmatch(r"[0-9a-f]{40}", args.git_base)
            or not _SHA.fullmatch(args.source_bundle_sha256) or args.config != "/etc/odoo/runner.conf"
            or args.artifacts != "/mnt/runner-artifacts" or args.secret_directory != "/run/runner-secrets"
            or (args.mode == "materialize") != (args.fixture_ref is not None)
            or args.with_approval_binding and args.mode != "materialize"
            or args.mode != "capture" and args.capture_label != "baseline"):
        raise SystemExit("PILOT_RESET_INVALID_CONFIGURATION")
    logging.disable(logging.CRITICAL)
    try:
        import odoo
        from odoo.orm.registry import Registry
        odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
        _require(not odoo.tools.config["test_enable"])
        registry = Registry(args.database)
        globals()[args.mode](registry, args)
    except Exception as error:
        allowed = {"pilot_reset_native.py", "pilot_approval_native.py", "runner_pilot_seed_native.py", "runner_pilot_alternatives_native.py",
                   "runner_pilot_a3a_origin_native.py", "runner_observed_fixture.py", "company_capture_native.py"}
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).name in allowed]
        category = type(error).__name__
        diagnostic = {"schema_version": "pilot-reset-native-failure/v1", "status": "FAIL", "mode": args.mode,
            "source_file": Path(frames[-1].filename).name if frames else "external-runtime",
            "source_line": frames[-1].lineno if frames else None,
            "category": category if category in {"ValueError", "TypeError", "KeyError", "AttributeError", "ProbeFailure",
                "CompanyCaptureError", "PilotSeedError", "ImportError", "ModuleNotFoundError", "FileNotFoundError",
                "PermissionError", "AccessError", "ValidationError", "AssertionError"} else "OTHER_RUNTIME_FAILURE"}
        try:
            _write(Path(args.artifacts) / "failure.json", diagnostic)
        except OSError:
            pass
        print("PILOT_RESET_NATIVE_FAILED_" + args.mode.upper())
        raise SystemExit(1) from None
    print("PILOT_RESET_NATIVE_PASS_" + args.mode.upper())


if __name__ == "__main__":
    main()

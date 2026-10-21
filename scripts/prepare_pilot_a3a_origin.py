"""Compile/check local A3a origin inputs, not approvals or scientific runs."""

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))

from tcc_gateway import run_record_store as fs
from tcc_gateway.pilot_dataset import read_pilot_cohort
from tcc_gateway.pilot_a3a_origin import prepare_origin_input, verify_extraction
from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES, PilotA3aOriginInput
from tcc_gateway.state import canonical_json_bytes


def read_package(path):
    parent, identity = fs._root(path.parent)
    fs._portable_component(path.name)
    package = PilotA3aOriginInput(fs._read_bounded(path, MAX_ORIGIN_BYTES))
    verify_extraction(package)
    fs._verify_directory(parent, identity)
    return package


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--cohort-root", type=Path)
    operation.add_argument("--check", type=Path)
    parser.add_argument("--cohort-sha256")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.check is not None:
            if args.cohort_sha256 is not None or args.output_root is not None:
                raise ValueError()
            package = read_package(args.check)
        else:
            if args.cohort_sha256 is None or args.output_root is None:
                raise ValueError()
            cohort = read_pilot_cohort(args.cohort_root, args.cohort_sha256)
            codebook = hashlib.sha256((ROOT / "dataset/codebook.md").read_text(
                encoding="utf-8-sig").encode("utf-8")).hexdigest()
            if cohort.codebook_sha256 != codebook:
                raise ValueError()
            package = prepare_origin_input(cohort)
            output, identity = fs._root(args.output_root)
            path = output / (package.sha256 + ".json")
            fs._write_exclusive(path, package._encoded)
            fs._verify_directory(output, identity)
            if read_package(path) != package:
                raise ValueError()
        value = package.to_mapping()
        print(canonical_json_bytes({"status": "PASS", "origin_input_sha256": package.sha256,
            **{name: value[name] for name in ("seed_sha256", "cohort_sha256", "codebook_sha256")},
            "fixture_count": 4, "counterpart_count": 4, "human_review_complete": False,
            "scientific_execution_allowed": False, "approval_generated": False}).decode("utf-8"))
        return 0
    except Exception:
        print('{"status":"FAIL","code":"PILOT_A3A_ORIGIN_INVALID"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Prepare/check local candidate business seed; never model/ERP execution."""

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))

from tcc_gateway import run_record_store as fs
from tcc_gateway.pilot_dataset import read_pilot_cohort
from tcc_gateway.pilot_seed import prepare_business_seed
from tcc_gateway.pilot_seed_contract import (
    MAX_SEED_BYTES, PilotBusinessSeed, MAX_ALTERNATIVES_BYTES, PilotAlternativeCatalog,
    validate_alternatives, parse_alternative_source,
)
from tcc_gateway.state import canonical_json_bytes


def read_seed(path):
    parent, identity = fs._root(path.parent)
    fs._portable_component(path.name)
    seed = PilotBusinessSeed(fs._read_bounded(path, MAX_SEED_BYTES))
    fs._verify_directory(parent, identity)
    return seed


def read_alternatives(path, seed):
    parent, identity = fs._root(path.parent)
    fs._portable_component(path.name)
    catalog = PilotAlternativeCatalog(fs._read_bounded(path, MAX_ALTERNATIVES_BYTES))
    validate_alternatives(seed, catalog)
    fs._verify_directory(parent, identity)
    return catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--cohort-root", type=Path)
    operation.add_argument("--check", type=Path)
    operation.add_argument("--check-alternatives", type=Path)
    operation.add_argument("--alternatives-source", type=Path)
    parser.add_argument("--seed-file", type=Path)
    parser.add_argument("--cohort-sha256")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.check_alternatives is not None or args.alternatives_source is not None:
            if args.seed_file is None or args.cohort_sha256 is not None:
                raise ValueError()
            seed = read_seed(args.seed_file)
            if args.check_alternatives is not None:
                if args.output_root is not None:
                    raise ValueError()
                catalog = read_alternatives(args.check_alternatives, seed)
            else:
                if args.output_root is None:
                    raise ValueError()
                source, identity = fs._root(args.alternatives_source.parent)
                fs._portable_component(args.alternatives_source.name)
                catalog = parse_alternative_source(fs._read_bounded(args.alternatives_source, MAX_ALTERNATIVES_BYTES))
                validate_alternatives(seed, catalog)
                fs._verify_directory(source, identity)
                output, identity = fs._root(args.output_root)
                path = output / (catalog.sha256 + ".json")
                fs._write_exclusive(path, catalog._encoded)
                fs._verify_directory(output, identity)
                if read_alternatives(path, seed) != catalog:
                    raise ValueError()
            value = catalog.to_mapping()
            print(canonical_json_bytes({"status": "PASS", "catalog_sha256": catalog.sha256,
                "seed_sha256": seed.sha256, "cohort_sha256": value["cohort_sha256"],
                "codebook_sha256": value["codebook_sha256"], "bank_count": len(value["banks"]),
                "vendor_count": len(value["vendor_refs"]), "order_count": len(value["purchase_order_checks"]),
                "human_review_complete": False, "scientific_execution_allowed": False}).decode("utf-8"))
            return 0
        if args.seed_file is not None:
            raise ValueError()
        if args.check is not None:
            if args.cohort_sha256 is not None or args.output_root is not None:
                raise ValueError()
            seed = read_seed(args.check)
        else:
            if args.cohort_sha256 is None or args.output_root is None:
                raise ValueError()
            cohort = read_pilot_cohort(args.cohort_root, args.cohort_sha256)
            codebook_hash = hashlib.sha256((ROOT / "dataset/codebook.md").read_text(
                encoding="utf-8-sig").encode("utf-8")).hexdigest()
            if cohort.codebook_sha256 != codebook_hash:
                raise ValueError()
            seed = prepare_business_seed(cohort)
            output, identity = fs._root(args.output_root)
            path = output / (seed.sha256 + ".json")
            fs._write_exclusive(path, seed._encoded)
            fs._verify_directory(output, identity)
            if read_seed(path) != seed:
                raise ValueError()
        value = seed.to_mapping()
        print(canonical_json_bytes({"status": "PASS", "seed_sha256": seed.sha256,
            "cohort_sha256": value["cohort_sha256"], "codebook_sha256": value["codebook_sha256"],
            "fixture_count": len(value["fixtures"]), "human_review_complete": False,
            "scientific_execution_allowed": False}).decode("utf-8"))
        return 0
    except Exception:
        print('{"status":"FAIL","code":"PILOT_BUSINESS_SEED_INVALID"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

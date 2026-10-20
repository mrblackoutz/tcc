# SPDX-License-Identifier: LGPL-3.0-or-later
"""Opt-in DEC-054 entry point; private native phases and real read-only gateway."""

import argparse
import json
import logging
from pathlib import Path
import re
import traceback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "candidate", "observe", "policy", "execute", "confirm",
                                         "dataset-fixtures-prepare", "dataset-fixtures", "dataset-fixtures-confirm"))
    parser.add_argument("--database", required=True)
    parser.add_argument("--config", default="/etc/odoo/runner.conf")
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    parser.add_argument("--secret-directory", default="/run/runner-secrets")
    parser.add_argument("--git-base", required=True)
    parser.add_argument("--source-bundle-sha256", required=True)
    parser.add_argument("--dataset-fixture-mode", action="store_true")
    args = parser.parse_args()
    if (re.fullmatch(r"tcc_runner_[0-9a-f]{12}", args.database) is None
            or re.fullmatch(r"[0-9a-f]{40}", args.git_base) is None
            or re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256) is None
            or args.config != "/etc/odoo/runner.conf"
            or args.artifacts != "/mnt/runner-artifacts"
            or args.secret_directory != "/run/runner-secrets"):
        raise SystemExit("RUNNER_OBSERVED_INVALID_CONFIGURATION")
    logging.disable(logging.CRITICAL)
    try:
        if args.mode in {"candidate", "policy"}:
            from runner_observed_gateway import run
        elif args.mode == "dataset-fixtures":
            from runner_dataset_fixture_gateway import run
        elif args.mode in {"dataset-fixtures-prepare", "dataset-fixtures-confirm"}:
            from runner_dataset_fixture_native import run
        else:
            from runner_observed_fixture import run
        run(args)
    except Exception as error:
        allowed_types = {"ProbeFailure", "ValueError", "TypeError", "KeyError", "AttributeError",
                         "PermissionError", "ImportError", "ModuleNotFoundError", "AccessError",
                         "ValidationError", "RegisteredExecutionError", "WorkflowRegistryError",
                         "OperationalObservationError", "AssertionError", "DatasetFixtureError", "ObservedRunnerError",
                         "DatasetFixtureProbeError"}
        allowed_files = {"runner_observed_native.py", "runner_observed_fixture.py",
                         "runner_observed_gateway.py", "c111_transactions.py",
                         "operational_observation_transactions.py", "runner_dataset_fixture_native.py",
                         "runner_dataset_fixture_gateway.py"}
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).name in allowed_files]
        diagnostic = {"schema_version": "runner-observed-failure/v1", "status": "FAIL", "mode": args.mode,
                      "category": type(error).__name__ if type(error).__name__ in allowed_types else "OTHER_RUNTIME_FAILURE",
                      "source_file": Path(frames[-1].filename).name if frames else "external-runtime",
                      "source_line": frames[-1].lineno if frames else None}
        try:
            (Path(args.artifacts) / ("observed-failure-" + args.mode + ".json")).write_text(
                json.dumps(diagnostic, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass
        if args.dataset_fixture_mode:
            # Separate opt-in finite metadata; never error messages, records,
            # credentials, arguments or frame locals. Preserve the v1 above.
            locations, current = [], error
            safe_files = allowed_files | {"workflow_registry.py", "draft_kernel.py", "identity.py"}
            for _depth in range(4):
                if current is None:
                    break
                for frame in traceback.extract_tb(current.__traceback__):
                    if Path(frame.filename).name in safe_files:
                        locations.append({"source_file": Path(frame.filename).name, "source_line": frame.lineno})
                current = current.__cause__ or current.__context__
            code = getattr(error, "code", None)
            known_codes = {"CONTRACT_INVALID", "EXECUTOR_IDENTITY_INVALID", "WORKFLOW_STATE_INVALID",
                           "BANK_NOT_ALLOWED", "REGISTRATION_DEFAULTS_INVALID", "REGISTRATION_UNAVAILABLE"}
            detail = {"schema_version": "dataset-fixture-failure/v1", "status": "FAIL", "mode": args.mode,
                      "code": code if type(code) is str and code in known_codes else "UNCLASSIFIED",
                      "locations": locations[-16:]}
            try:
                (Path(args.artifacts) / "dataset-fixture-failure.json").write_text(
                    json.dumps(detail, sort_keys=True) + "\n", encoding="utf-8")
            except OSError:
                pass
        print("RUNNER_OBSERVED_FAILED_" + args.mode.upper())
        raise SystemExit(1) from None
    print("RUNNER_OBSERVED_PASS_" + args.mode.upper())


if __name__ == "__main__":
    main()

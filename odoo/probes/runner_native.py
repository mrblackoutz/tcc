# SPDX-License-Identifier: LGPL-3.0-or-later
"""Entrypoint for the labelled disposable native runner proof (DEC-051).

Odoo preparation/observation and gateway dispatch run in separate cached images.
No SQL commit, JSON-2 transport or native financial method is mocked.
Only the model provider response is synthetic. This is not a scientific run.
"""

import argparse
import json
import logging
from pathlib import Path
import re
import traceback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "dispatch", "observe", "c1"))
    parser.add_argument("--database", required=True)
    parser.add_argument("--config", default="/etc/odoo/runner.conf")
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    parser.add_argument("--secret-directory", default="/run/runner-secrets")
    parser.add_argument("--git-base", required=True)
    parser.add_argument("--source-bundle-sha256", required=True)
    args = parser.parse_args()
    if (re.fullmatch(r"tcc_runner_[0-9a-f]{12}", args.database) is None
            or re.fullmatch(r"[0-9a-f]{40}", args.git_base) is None
            or re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256) is None
            or args.config != "/etc/odoo/runner.conf"
            or args.artifacts != "/mnt/runner-artifacts"
            or args.secret_directory != "/run/runner-secrets"):
        raise SystemExit("RUNNER_NATIVE_INVALID_CONFIGURATION")
    logging.disable(logging.CRITICAL)
    # Never print a traceback, database error, response body or credential.
    try:
        if args.mode == "dispatch":
            from runner_native_gateway import dispatch
            dispatch(args)
        else:
            from runner_native_fixture import run
            run(args)
    except Exception as error:
        # Bounded diagnostic metadata only. Never serialize exception args,
        # values, traceback source lines or locals (these may hold the key).
        allowed_types = {"ProbeFailure", "ValueError", "TypeError", "KeyError", "AttributeError",
                         "PermissionError", "ImportError", "ModuleNotFoundError", "AccessError",
                         "ValidationError", "RegisteredExecutionError", "WorkflowRegistryError"}
        allowed_files = {"runner_native.py", "runner_native_fixture.py",
                         "runner_native_gateway.py", "c111_transactions.py"}
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).name in allowed_files]
        diagnostic = {"schema_version": "runner-native-failure/v1", "status": "FAIL",
                      "mode": args.mode,
                      "category": type(error).__name__ if type(error).__name__ in allowed_types else "OTHER_RUNTIME_FAILURE",
                      "source_file": Path(frames[-1].filename).name if frames else "external-runtime",
                      "source_line": frames[-1].lineno if frames else None}
        try:
            (Path(args.artifacts) / ("failure-" + args.mode + ".json")).write_text(
                json.dumps(diagnostic, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass
        print("RUNNER_NATIVE_FAILED_" + args.mode.upper())
        raise SystemExit(1) from None
    print("RUNNER_NATIVE_PASS_" + args.mode.upper())


if __name__ == "__main__":
    main()

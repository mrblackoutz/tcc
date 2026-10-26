# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-079 fixed Linux sampler: one closed JSON value, no paths or secrets."""

import json
import sys


def main(argv=None):
    # This probe accepts no arguments. Avoid argparse's echo of received values
    # on a misuse/failure path, including arbitrary path or credential strings.
    if argv is None:
        argv = sys.argv[1:]
    try:
        if type(argv) is not list or argv:
            raise ValueError
        from tcc_gateway.linux_clock_domain import sample_clock
        value = sample_clock()
        sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
        sys.stdout.flush()
    except Exception:
        sys.stderr.write("LINUX_CLOCK_SAMPLE_FAILED\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

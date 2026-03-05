from __future__ import annotations

import sys


def main() -> int:
    from myrecorder.app import run as app_main

    argv = list(sys.argv[1:])
    has_log_level = any(
        arg == "--log-level" or arg.startswith("--log-level=")
        for arg in argv
    )
    if not has_log_level:
        argv.extend(["--log-level", "DEBUG"])
    return int(app_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())

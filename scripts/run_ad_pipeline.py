"""Quarantined compatibility entry point for the former zodiac pipeline."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "HOLD_LEGACY_ZODIAC_PIPELINE_ISOLATED: no generation or upload is available",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

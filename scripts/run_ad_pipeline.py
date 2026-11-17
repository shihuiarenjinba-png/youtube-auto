from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "channels.example.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube advertisement pipeline scaffold")
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.dry_run:
        raise SystemExit(
            "Production upload is intentionally disabled in the scaffold. "
            "Port and validate the proven uploader before enabling it."
        )

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    lane = config["languages"][args.language]

    print(
        json.dumps(
            {
                "status": "SCAFFOLD_DRY_RUN_OK",
                "language": args.language,
                "lane": lane,
                "upload_performed": False,
                "next_step": "Port the proven production generator/uploader and validate secrets.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

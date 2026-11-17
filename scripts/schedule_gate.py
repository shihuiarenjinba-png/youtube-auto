"""Timezone-aware gate for GitHub's UTC-only cron scheduler."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "lanes.json"


def selected_cron(language: str, local_date: date) -> str:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    lane = config["languages"][language]
    hour, minute = (int(value) for value in lane["local_post_time"].split(":"))
    target_local = datetime.combine(
        local_date,
        time(hour=hour, minute=minute),
        tzinfo=ZoneInfo(lane["timezone"]),
    )
    target_utc = target_local.astimezone(timezone.utc)
    return f"{target_utc.minute} {target_utc.hour} * * *"


def should_run(language: str, event_cron: str, now_utc: datetime | None = None) -> bool:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    lane = config["languages"][language]
    if event_cron not in lane["cron_candidates_utc"]:
        return False
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_date = current.astimezone(ZoneInfo(lane["timezone"])).date()
    return event_cron == selected_cron(language, local_date)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    parser.add_argument("--event-cron", required=True)
    args = parser.parse_args()
    allowed = should_run(args.language, args.event_cron)
    payload = {
        "language": args.language,
        "event_cron": args.event_cron,
        "selected": allowed,
    }
    print(json.dumps(payload))
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"selected={'true' if allowed else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

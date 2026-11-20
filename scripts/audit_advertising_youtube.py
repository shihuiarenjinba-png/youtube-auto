from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.read_only_youtube import ReadOnlyYouTubeIdentityClient  # noqa: E402


CONFIG_PATH = ROOT / "config" / "account_namespaces.json"


def load_config(market: str) -> tuple[dict, set[str]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    zodiac_ids = {
        str(config["zodiac"][lane]["channel_id"])
        for lane in ("ja", "en")
    }
    lane = config["advertising"].get(market)
    if not isinstance(lane, dict):
        raise RuntimeError("HOLD_ADVERTISING_LANE_MISSING")
    return lane, zodiac_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only advertising YouTube identity check")
    parser.add_argument("--market", choices=("jp", "us"), required=True)
    args = parser.parse_args()

    lane, zodiac_ids = load_config(args.market)
    expected = str(lane.get("expected_channel_id") or "").strip()
    if not expected:
        raise RuntimeError(str(lane.get("identity_status") or "HOLD_AD_CHANNEL_UNKNOWN"))
    if expected in zodiac_ids:
        raise RuntimeError("HOLD_ZODIAC_CHANNEL_CONFIGURED_AS_ADVERTISING")

    secret_names = lane["secret_names"]
    identity = ReadOnlyYouTubeIdentityClient(
        client_id_env=secret_names["client_id"],
        client_secret_env=secret_names["client_secret"],
        refresh_token_env=secret_names["refresh_token"],
    ).check()
    if identity.channel_id in zodiac_ids:
        raise RuntimeError("HOLD_ZODIAC_OAUTH_PRESENTED_TO_ADVERTISING_LANE")
    if identity.channel_id != expected:
        raise RuntimeError("HOLD_ADVERTISING_CHANNEL_ID_MISMATCH")

    print(json.dumps({
        "status": "ADVERTISING_OAUTH_IDENTITY_PASS",
        "namespace": f"advertising.{args.market}",
        "account_number": lane["local_account_number"],
        "actual_channel_id": identity.channel_id,
        "actual_channel_title": identity.title,
        "write_performed": False,
        "token_persisted": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # fail closed without echoing OAuth response details
        value = str(exc)
        status = value if value.startswith("HOLD_") else "HOLD_OAUTH_READ_ONLY_CHECK_FAILED"
        print(json.dumps({
            "status": status,
            "write_performed": False,
            "token_persisted": False,
            "fallback_performed": False,
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2) from None

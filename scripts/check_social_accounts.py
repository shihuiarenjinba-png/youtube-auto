from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.actions_zernio import ActionsZernioClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Instagram/TikTok account validation")
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    args = parser.parse_args()

    config = json.loads((ROOT / "config" / "social_lanes.json").read_text(encoding="utf-8"))
    lane = config["languages"][args.language]
    if config.get("namespace") != "advertising.social" or config.get("fallback_policy") != "DENY":
        raise RuntimeError("Social advertising namespace/fallback policy is invalid")
    if lane.get("purpose") != "advertising":
        raise RuntimeError("Social lane purpose is not advertising")
    results: list[dict] = []
    errors: list[dict] = []
    for platform in ("instagram", "tiktok"):
        for entry in lane[platform]:
            if entry.get("purpose") != "advertising":
                raise RuntimeError("Zernio account purpose is not advertising")
            account_id = str(entry["account_id"])
            credential_env = str(entry["credential_env"])
            try:
                client = ActionsZernioClient(
                    config["base_url"],
                    os.environ.get(credential_env, ""),
                )
                health = client.account_health(account_id)
                if health["account_id"] != account_id:
                    raise RuntimeError("Zernio credential/account identity mismatch")
                if health["platform"] and str(health["platform"]).lower() != platform:
                    raise RuntimeError("Zernio platform identity mismatch")
                if (
                    health["status"] == "error"
                    or health["can_post"] is not True
                    or health["token_valid"] is not True
                    or health["needs_reconnect"] is True
                ):
                    raise RuntimeError("Zernio account is not ready to post")
                item = {"platform": platform, **health}
                if platform == "tiktok":
                    capacity = client.tiktok_capacity(account_id)
                    item["capacity"] = capacity
                    if capacity["can_post_more"] is not True:
                        raise RuntimeError("TIKTOK_CAPACITY_WAIT")
                results.append(item)
            except Exception as exc:
                errors.append({
                    "platform": platform,
                    "account_id": account_id,
                    "error": type(exc).__name__,
                })

    print(json.dumps({
        "status": "SOCIAL_HEALTH_OK" if not errors else "SOCIAL_HEALTH_FAILED",
        "language": args.language,
        "market": lane["market"],
        "accounts": results,
        "errors": errors,
        "post_performed": False,
    }, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

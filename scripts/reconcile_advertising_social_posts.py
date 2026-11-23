from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.actions_zernio import ActionsZernioClient  # noqa: E402


CONFIG_PATH = ROOT / "config" / "social_lanes.json"


class ReconciliationHold(RuntimeError):
    pass


def _extract_post(response: dict[str, Any]) -> dict[str, Any]:
    for key in ("post", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            nested = value.get("post")
            if isinstance(nested, dict):
                return nested
            if isinstance(value.get("platforms"), list):
                return value
    return response


def resolve_advertising_account(
    config: dict[str, Any], *, language: str, platform: str, account_id: str
) -> dict[str, str]:
    if config.get("namespace") != "advertising.social" or config.get("fallback_policy") != "DENY":
        raise ReconciliationHold("HOLD_SOCIAL_NAMESPACE_INVALID")
    languages = config.get("languages")
    lane = languages.get(language) if isinstance(languages, dict) else None
    if not isinstance(lane, dict) or lane.get("purpose") != "advertising":
        raise ReconciliationHold("HOLD_ADVERTISING_LANE_MISSING")
    if platform not in {"instagram", "tiktok"}:
        raise ReconciliationHold("HOLD_UNSUPPORTED_PLATFORM")
    rows = lane.get(platform)
    if not isinstance(rows, list):
        raise ReconciliationHold("HOLD_PLATFORM_LANE_MISSING")
    matches = [
        row for row in rows
        if isinstance(row, dict) and str(row.get("account_id") or "") == account_id
    ]
    if len(matches) != 1:
        raise ReconciliationHold("HOLD_ACCOUNT_NOT_EXACTLY_ONE")
    row = matches[0]
    if (
        row.get("purpose") != "advertising"
        or row.get("market") != lane.get("market")
        or row.get("platform") != platform
    ):
        raise ReconciliationHold("HOLD_ACCOUNT_NAMESPACE_MISMATCH")
    credential_env = str(row.get("credential_env") or "")
    if credential_env not in {"ZERNIO_API_KEY_1", "ZERNIO_API_KEY_2"}:
        raise ReconciliationHold("HOLD_CREDENTIAL_SCOPE_INVALID")
    return {
        "market": str(lane["market"]),
        "credential_env": credential_env,
        "account_id": account_id,
        "platform": platform,
    }


def _public_https_url(value: Any) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or host == "zernio.com" or host.endswith(".zernio.com"):
        return ""
    return candidate


def build_reconciliation_result(
    response: dict[str, Any],
    *,
    platform: str,
    account_id: str,
    zernio_post_id: str,
    allow_account_id_omission: bool = False,
) -> dict[str, Any]:
    post = _extract_post(response)
    rows = post.get("platforms")
    if not isinstance(rows, list):
        raise ReconciliationHold("HOLD_PLATFORM_RESULT_MISSING")
    targets = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("platform") or "").lower() == platform
    ]
    if len(targets) != 1:
        raise ReconciliationHold("HOLD_POST_PLATFORM_NOT_EXACTLY_ONE")
    target = targets[0]
    response_account_id = str(
        target.get("accountId")
        or target.get("account_id")
        or target.get("socialAccountId")
        or ""
    )
    if response_account_id and response_account_id != account_id:
        raise ReconciliationHold("HOLD_POST_ACCOUNT_PLATFORM_MISMATCH")
    if not response_account_id and not allow_account_id_omission:
        raise ReconciliationHold("HOLD_POST_ACCOUNT_ID_NOT_RETURNED")
    account_verification_source = (
        "zernio_post_response" if response_account_id else "original_creation_run_arguments"
    )
    status = str(target.get("status") or post.get("status") or "").strip().lower()
    if status != "published":
        raise ReconciliationHold("HOLD_SOCIAL_POST_NOT_PUBLISHED")
    public_url = ""
    for key in ("platformPostUrl", "publishedUrl", "permalink", "platformUrl", "url"):
        public_url = _public_https_url(target.get(key))
        if public_url:
            break
    if not public_url:
        for key in ("platformPostUrl", "publishedUrl", "permalink", "platformUrl", "url"):
            public_url = _public_https_url(post.get(key))
            if public_url:
                break
    return {
        "status": "SOCIAL_POST_PUBLISHED_URL_CONFIRMED" if public_url else "SOCIAL_POST_PUBLISHED_URL_PENDING",
        "platform": platform,
        "account_id": account_id,
        "account_verification_source": account_verification_source,
        "zernio_post_id": zernio_post_id,
        "platform_post_id": str(target.get("platformPostId") or ""),
        "post_status": status,
        "published_at": target.get("publishedAt") or post.get("publishedAt") or "",
        "published_url": public_url,
        "public_url_confirmed": bool(public_url),
        "read_only": True,
        "write_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only reconciliation of a known Zernio social post")
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    parser.add_argument("--platform", choices=("instagram", "tiktok"), required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--post-id", required=True, help="Zernio post ID, not a platform-native ID")
    parser.add_argument(
        "--allow-account-id-omission",
        action="store_true",
        help="Allow only pre-verified historical posts whose original creation run pins the account ID",
    )
    args = parser.parse_args()

    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        account = resolve_advertising_account(
            config,
            language=args.language,
            platform=args.platform,
            account_id=args.account_id,
        )
        api_key = os.environ.get(account["credential_env"], "")
        client = ActionsZernioClient(config["base_url"], api_key)
        response = client.get_post(args.post_id)
        result = build_reconciliation_result(
            response,
            platform=args.platform,
            account_id=args.account_id,
            zernio_post_id=args.post_id,
            allow_account_id_omission=args.allow_account_id_omission,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, ReconciliationHold, RuntimeError) as exc:
        print(json.dumps({
            "status": str(exc) if str(exc).startswith("HOLD_") else "HOLD_SOCIAL_POST_RECONCILIATION_FAILED",
            "read_only": True,
            "write_performed": False,
        }, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

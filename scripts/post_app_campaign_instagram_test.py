from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.actions_zernio import ActionsZernioClient, ZernioValidationError  # noqa: E402
from core.app_ad_video import AppVideoHold, build_local_review_video  # noqa: E402
from core.app_campaigns import (  # noqa: E402
    CampaignHold,
    build_grounded_dataset,
    generate_app_ad_content,
    load_campaign,
)
from core.advertising_rag import RagHold  # noqa: E402
from core.social_posting_policy import idempotency_key, validate_preflight  # noqa: E402


def _extract_post(response: dict[str, Any]) -> dict[str, Any]:
    for key in ("post", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            if isinstance(value.get("post"), dict):
                return value["post"]
            return value
    return response


def _post_id(value: dict[str, Any]) -> str:
    return str(value.get("id") or value.get("_id") or value.get("postId") or "")


def _status(value: dict[str, Any]) -> str:
    return str(value.get("status") or "").strip().lower()


def _platform_failure(value: dict[str, Any]) -> str:
    platforms = value.get("platforms")
    if not isinstance(platforms, list):
        return ""
    for row in platforms:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").lower()
        error = str(row.get("errorMessage") or row.get("error") or "")
        if status == "failed" or error:
            return error or "platform status failed"
    return ""


def _published_url(value: dict[str, Any]) -> str:
    candidates = []
    for key in ("platformPostUrl", "url", "postUrl", "permalink", "platformUrl", "publishedUrl"):
        if value.get(key):
            candidates.append(str(value[key]))
    platforms = value.get("platforms")
    if isinstance(platforms, list):
        for row in platforms:
            if isinstance(row, dict):
                for key in ("url", "postUrl", "permalink", "platformUrl", "publishedUrl"):
                    if row.get(key):
                        candidates.append(str(row[key]))
    for url in candidates:
        if url.startswith("https://") and "media.zernio.com" not in url:
            return url
    return ""


def _platform_post_id(value: dict[str, Any], *, platform: str, account_id: str) -> str:
    platforms = value.get("platforms")
    if not isinstance(platforms, list):
        return ""
    matches = [
        row for row in platforms
        if isinstance(row, dict)
        and str(row.get("platform") or "").lower() == platform
        and str(row.get("accountId") or row.get("account_id") or "") == account_id
    ]
    if len(matches) != 1:
        return ""
    return str(matches[0].get("platformPostId") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase C: one controlled social app-ad post")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--platform", choices=["instagram", "tiktok"], required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--language", choices=["ja"], default="ja")
    parser.add_argument("--zernio-base-url", default="https://zernio.com/api/v1")
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="daymark-phase-c-instagram-"))
    output = temp_root / "daymark-ai-instagram-test.mp4"
    cards = temp_root / "cards"
    post_created = False

    try:
        campaign = load_campaign(args.dataset)
        grounded = build_grounded_dataset(campaign)
        content = generate_app_ad_content(grounded)
        if not content.get("posting_eligible"):
            raise CampaignHold("HOLD_CAMPAIGN_NOT_POSTING_ELIGIBLE")

        social = json.loads((ROOT / "config" / "social_lanes.json").read_text(encoding="utf-8"))
        lane = social["languages"][args.language]
        matches = [row for row in lane[args.platform] if row.get("account_id") == args.account_id]
        if len(matches) != 1:
            raise ValueError("HOLD_CONTROLLED_ACCOUNT_NOT_EXACTLY_ONE")
        account = matches[0]
        credential_env = str(account.get("credential_env") or "")
        if credential_env != "ZERNIO_API_KEY_1":
            raise ValueError("HOLD_CONTROLLED_CREDENTIAL_SCOPE_MISMATCH")

        api_key = os.environ.get(credential_env, "")
        client = ActionsZernioClient(args.zernio_base_url, api_key)
        health = client.account_health(args.account_id)
        if health.get("account_id") and health.get("account_id") != args.account_id:
            raise ValueError("HOLD_ACCOUNT_IDENTITY_MISMATCH")

        validation = build_local_review_video(
            campaign,
            content,
            root=ROOT,
            output_path=output,
            cards_dir=cards,
        )
        media = client.upload_temp_media(output)

        tiktok_ok = True
        if args.platform == "tiktok":
            capacity = client.tiktok_capacity(args.account_id)
            can_post_more = capacity.get("can_post_more")
            max_duration = int(capacity.get("max_video_duration_seconds") or 0)
            tiktok_ok = can_post_more is not False and max_duration >= int(validation["duration_seconds"])

        validate_preflight(
            campaign=grounded,
            account=account,
            platform=args.platform,
            media_valid=True,
            duplicate_found=False,
            capacity_ok=bool(
                health.get("can_post")
                and health.get("token_valid")
                and not health.get("needs_reconnect")
                and tiktok_ok
            ),
            posts_today=0,
            last_posted_at=None,
            now=datetime.now(timezone.utc),
        )

        caption = content["caption"] + "\n" + " ".join(content.get("hashtags") or [])
        idem = idempotency_key(
            campaign_id=str(campaign["campaign_id"]),
            source_hash=str(grounded["generated_from_source_hash"]),
            video_hash=str(validation["video_sha256"]),
            platform=args.platform,
            account_id=args.account_id,
        )
        response = client.create_video_post_now(
            platform=args.platform,
            account_id=args.account_id,
            content=caption,
            media_url=str(media["public_url"]),
            idempotency_key=idem,
        )
        post_created = True
        post = _extract_post(response)
        failure = _platform_failure(post)
        if failure or _status(post) == "failed":
            raise ZernioValidationError("HOLD_CONTROLLED_POST_FAILED")

        pid = _post_id(post) or _post_id(response)
        current = post
        if pid:
            for _ in range(18):
                status = _status(current)
                if status in {"published", "failed"}:
                    break
                time.sleep(5)
                current = _extract_post(client.get_post(pid))
                failure = _platform_failure(current)
                if failure or _status(current) == "failed":
                    raise ZernioValidationError("HOLD_CONTROLLED_POST_FAILED")

        result = {
            "status": "APP_CAMPAIGN_SOCIAL_CONTROLLED_POST_PASS",
            "campaign_id": campaign["campaign_id"],
            "app_id": campaign["app_id"],
            "platform": args.platform,
            "account_id": args.account_id,
            "post_id": pid,
            "platform_post_id": _platform_post_id(current, platform=args.platform, account_id=args.account_id) or _platform_post_id(post, platform=args.platform, account_id=args.account_id),
            "post_status": _status(current) or _status(post) or "created",
            "published_url": _published_url(current) or _published_url(post),
            "store_url": campaign.get("store_url") or "",
            "generated_from_source_hash": grounded["generated_from_source_hash"],
            "evidence_hash": grounded["evidence_hash"],
            "video_sha256": validation["video_sha256"],
            "idempotency_key_sha256": __import__("hashlib").sha256(idem.encode("utf-8")).hexdigest(),
            "media_upload_performed": True,
            "social_post_created": True,
            "social_post_performed": True,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (CampaignHold, RagHold, AppVideoHold, ZernioValidationError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({
            "status": str(exc),
            "social_post_created": post_created,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
            "fallback_performed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

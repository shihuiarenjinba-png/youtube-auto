from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app_ad_video import AppVideoHold, build_local_review_video  # noqa: E402
from core.app_campaigns import CampaignHold  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local-only grounded app advertisement review video")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cards_dir = args.output.parent / f".{args.output.stem}-cards"
    manifest_path = args.output.with_suffix(".manifest.json")
    try:
        campaign = json.loads(args.dataset.read_text(encoding="utf-8"))
        review = json.loads(args.review.read_text(encoding="utf-8"))
        if review.get("status") != "APP_CAMPAIGN_RAG_DRY_RUN_PASS":
            raise AppVideoHold("HOLD_RAG_REVIEW_NOT_PASSED")
        grounded = review.get("campaign") or {}
        if grounded.get("campaign_id") != campaign.get("campaign_id"):
            raise AppVideoHold("HOLD_REVIEW_CAMPAIGN_ID_MISMATCH")
        if grounded.get("grounding_status") != "PASS":
            raise AppVideoHold("HOLD_REVIEW_GROUNDING_NOT_PASSED")
        immutable_fields = (
            "app_id", "market", "language", "official_url", "source_urls",
            "screenshots", "hold_reasons",
        )
        if any(grounded.get(field) != campaign.get(field) for field in immutable_fields):
            raise AppVideoHold("HOLD_REVIEW_DATASET_MISMATCH")
        content = review.get("generated_content") or {}
        validation = build_local_review_video(
            campaign,
            content,
            root=ROOT,
            output_path=args.output,
            cards_dir=cards_dir,
        )
        manifest = {
            "status": "LOCAL_APP_AD_VIDEO_PASS",
            "campaign_id": campaign["campaign_id"],
            "app_id": campaign["app_id"],
            "market": campaign["market"],
            "language": campaign["language"],
            "evidence_hash": content["evidence_hash"],
            "generated_from_source_hash": content["generated_from_source_hash"],
            "posting_eligible": bool(content.get("posting_eligible")),
            "hold_reasons": content.get("hold_reasons") or [],
            "video": validation,
            "media_upload_performed": False,
            "social_post_created": False,
            "social_post_performed": False,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except (AppVideoHold, CampaignHold, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        args.output.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        print(json.dumps({
            "status": str(exc),
            "media_upload_performed": False,
            "social_post_created": False,
            "social_post_performed": False,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
            "fallback_performed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    finally:
        shutil.rmtree(cards_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

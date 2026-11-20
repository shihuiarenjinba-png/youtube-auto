from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app_campaigns import (  # noqa: E402
    CampaignHold,
    build_grounded_dataset,
    generate_app_ad_content,
    load_campaign,
)
from core.advertising_rag import RagHold  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-source app Campaign RAG dry-run")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        campaign = load_campaign(args.dataset)
        grounded = build_grounded_dataset(campaign)
        content = generate_app_ad_content(grounded)
        result = {
            "status": "APP_CAMPAIGN_RAG_DRY_RUN_PASS",
            "campaign": grounded,
            "generated_content": content,
            "generated_video_count": 0,
            "media_upload_performed": False,
            "social_post_performed": False,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
        }
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            print(json.dumps({
                "status": result["status"],
                "campaign_id": grounded["campaign_id"],
                "app_id": grounded["app_id"],
                "source_hashes": grounded["source_hashes"],
                "generated_from_source_hash": grounded["generated_from_source_hash"],
                "evidence_hash": grounded["evidence_hash"],
                "posting_eligible": grounded["posting_eligible"],
                "hold_reasons": grounded.get("hold_reasons") or [],
                "review_path": str(args.output),
                "generated_video_count": 0,
                "media_upload_performed": False,
                "social_post_created": False,
                "social_post_performed": False,
                "youtube_write_performed": False,
                "zodiac_write_performed": False,
            }, ensure_ascii=False, indent=2))
        else:
            print(rendered)
        return 0
    except (CampaignHold, RagHold) as exc:
        print(json.dumps({
            "status": str(exc),
            "generated_video_count": 0,
            "media_upload_performed": False,
            "social_post_performed": False,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
            "fallback_performed": False,
        }, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

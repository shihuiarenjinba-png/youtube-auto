"""Generate a Daymark ad-video preview bundle without social credentials or publishing."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from core.app_ad_video import build_local_review_video, write_video_review_bundle  # noqa: E402
from core.app_campaigns import (  # noqa: E402
    CampaignHold,
    build_grounded_dataset,
    generate_app_ad_content,
    load_campaign,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a local Daymark video preview and retain visual evidence only."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()

    work_dir = Path(tempfile.mkdtemp(prefix="daymark-review-preview-"))
    try:
        campaign = load_campaign(args.dataset)
        grounded = build_grounded_dataset(campaign)
        content = generate_app_ad_content(grounded)
        if not content.get("posting_eligible"):
            raise CampaignHold("HOLD_CAMPAIGN_NOT_POSTING_ELIGIBLE")

        video_path = work_dir / "daymark-ai-review.mp4"
        cards_dir = work_dir / "cards"
        validation = build_local_review_video(
            campaign,
            content,
            root=ROOT,
            output_path=video_path,
            cards_dir=cards_dir,
        )
        evidence_path = write_video_review_bundle(
            campaign,
            content,
            root=ROOT,
            cards_dir=cards_dir,
            video_path=video_path,
            evidence_dir=args.evidence_dir,
            validation=validation,
        )
        print(json.dumps({
            "status": "DAYMARK_VIDEO_REVIEW_BUNDLE_READY",
            "campaign_id": campaign["campaign_id"],
            "app_id": campaign["app_id"],
            "evidence_path": str(evidence_path),
            "video_sha256": validation["video_sha256"],
            "generation_mode": "screenshot_cards_crossfade_with_local_bgm",
            "image_generation_api_used": False,
            "voice_generation_api_used": False,
            "posting_performed": False,
            "zernio_called": False,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

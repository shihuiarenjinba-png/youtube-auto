from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase B: build one grounded app ad video and transfer it to Zernio media storage only")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--zernio-base-url", default="https://zernio.com/api/v1")
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="daymark-phase-b-"))
    output = temp_root / "daymark-ai-phase-b.mp4"
    cards = temp_root / "cards"

    try:
        campaign = load_campaign(args.dataset)
        grounded = build_grounded_dataset(campaign)
        content = generate_app_ad_content(grounded)
        if not content.get("posting_eligible"):
            raise CampaignHold("HOLD_CAMPAIGN_NOT_POSTING_ELIGIBLE")

        validation = build_local_review_video(
            campaign,
            content,
            root=ROOT,
            output_path=output,
            cards_dir=cards,
        )

        api_key = os.environ.get("ZERNIO_API_KEY_1", "")
        client = ActionsZernioClient(args.zernio_base_url, api_key)
        uploaded = client.upload_temp_media(output)

        public_url = str(uploaded.get("public_url") or "")
        parsed = urlparse(public_url)
        result = {
            "status": "APP_CAMPAIGN_PHASE_B_MEDIA_TRANSFER_PASS",
            "campaign_id": campaign["campaign_id"],
            "app_id": campaign["app_id"],
            "market": campaign["market"],
            "language": campaign["language"],
            "store_url": campaign.get("store_url") or "",
            "evidence_hash": grounded["evidence_hash"],
            "generated_from_source_hash": grounded["generated_from_source_hash"],
            "posting_eligible": True,
            "video": {
                "codec": validation["codec"],
                "width": validation["width"],
                "height": validation["height"],
                "audio_codec": validation["audio_codec"],
                "duration_seconds": validation["duration_seconds"],
                "video_sha256": validation["video_sha256"],
                "card_count": validation["card_count"],
            },
            "zernio": {
                "public_host": parsed.hostname or "",
                "public_url_sha256": _sha256_text(public_url),
                "storage_key_sha256": _sha256_text(str(uploaded.get("storage_key") or "")),
                "presign_succeeded": bool(uploaded.get("presign_succeeded")),
                "presigned_put_succeeded": bool(uploaded.get("presigned_put_succeeded")),
                "bytes": int(uploaded.get("bytes") or 0),
            },
            "media_upload_performed": True,
            "social_post_created": False,
            "social_post_performed": False,
            "youtube_write_performed": False,
            "zodiac_write_performed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (CampaignHold, RagHold, AppVideoHold, ZernioValidationError, OSError, ValueError, KeyError) as exc:
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
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

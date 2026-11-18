from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.actions_zernio import ActionsZernioClient  # noqa: E402
from core.auto_uploader import BGM_DIR, OUT_DIR, plan_sets, render_html_to_png  # noqa: E402
from core.bgm_picker import DEFAULT_AUTO_VOLUME, pick as pick_bgm  # noqa: E402
from core.card_video import build_card_video  # noqa: E402
from scripts.run_ad_pipeline import lane_card_check, validate_video  # noqa: E402


SOCIAL_CONFIG = ROOT / "config" / "social_lanes.json"
YOUTUBE_CONFIG = ROOT / "config" / "lanes.json"


def load_configs(language: str) -> tuple[dict, dict]:
    social = json.loads(SOCIAL_CONFIG.read_text(encoding="utf-8"))
    lanes = json.loads(YOUTUBE_CONFIG.read_text(encoding="utf-8"))
    social_lane = (social.get("languages") or {}).get(language)
    youtube_lane = (lanes.get("languages") or {}).get(language)
    if not isinstance(social_lane, dict) or not isinstance(youtube_lane, dict):
        raise RuntimeError("Lane configuration is missing")
    return social, {"social": social_lane, "youtube": youtube_lane}


def validate_accounts(config: dict, social_lane: dict) -> tuple[list[str], dict]:
    credential_names: set[str] = set()
    health_check_count = 0
    tiktok_capacity_check_count = 0
    for platform in ("instagram", "tiktok"):
        for entry in social_lane.get(platform) or []:
            account_id = str(entry["account_id"])
            credential_env = str(entry["credential_env"])
            credential_names.add(credential_env)
            client = ActionsZernioClient(config["base_url"], os.environ.get(credential_env, ""))
            health = client.account_health(account_id)
            if health["account_id"] != account_id:
                raise RuntimeError("Zernio credential/account identity mismatch")
            if str(health["platform"]).lower() != platform:
                raise RuntimeError("Zernio platform identity mismatch")
            if (
                health["status"] == "error"
                or health["can_post"] is not True
                or health["token_valid"] is not True
                or health["needs_reconnect"] is True
            ):
                raise RuntimeError("Zernio account is not ready")
            health_check_count += 1
            if platform == "tiktok":
                capacity = client.tiktok_capacity(account_id)
                if capacity["can_post_more"] is not True:
                    raise RuntimeError("TIKTOK_CAPACITY_WAIT")
                tiktok_capacity_check_count += 1
    if not credential_names:
        raise RuntimeError("No Zernio credentials are configured for this lane")
    if health_check_count == 0 or tiktok_capacity_check_count == 0:
        raise RuntimeError("Required Zernio health/capacity checks did not run")
    return sorted(credential_names), {
        "account_health_passed": True,
        "account_health_check_count": health_check_count,
        "tiktok_capacity_passed": True,
        "tiktok_capacity_check_count": tiktok_capacity_check_count,
    }


def remove_work_dir(work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    if work.exists():
        raise RuntimeError("Temporary media cleanup failed")


def build_probe_video(language: str, youtube_lane: dict) -> tuple[Path, dict]:
    logger = logging.getLogger("social-media-upload")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(logging.StreamHandler(sys.stdout))

    now = datetime.now(ZoneInfo(str(youtube_lane.get("timezone") or "Asia/Tokyo")))
    day = now.date()
    sets = plan_sets(language, day, 1, {}, logger)
    if len(sets) != 1:
        raise RuntimeError("Planner must return exactly one video for media probe")
    cards = sets[0]
    lane_card_check(cards, language)

    work = OUT_DIR / day.isoformat() / f"{language}-zernio-media-probe"
    try:
        pngs: list[str] = []
        for index, card in enumerate(cards, start=1):
            png = work / f"card{index:02d}.png"
            png.parent.mkdir(parents=True, exist_ok=True)
            if not render_html_to_png(str(card["html"]), png, logger):
                raise RuntimeError("HTML rendering failed")
            pngs.append(str(png))

        bgm = pick_bgm(BGM_DIR, seed=f"{day.isoformat()}:{language}:zernio-probe", uniform=True)
        if not bgm:
            raise RuntimeError("No proven BGM asset is available")
        mp4 = work / f"zernio_media_probe_{language}_{day.isoformat()}.mp4"
        if not build_card_video(
            pngs,
            str(mp4),
            bgm_path=bgm,
            volume=DEFAULT_AUTO_VOLUME,
            seconds_per_card=6.0,
            logger=logger,
        ):
            raise RuntimeError("Video encoding failed")
        return mp4, validate_video(mp4)
    except Exception:
        remove_work_dir(work)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload one generated MP4 to Zernio temporary storage without creating posts"
    )
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    args = parser.parse_args()

    config, lanes = load_configs(args.language)
    credential_names, account_validation = validate_accounts(config, lanes["social"])
    mp4: Path | None = None
    work: Path | None = None
    uploads: list[dict] = []
    try:
        mp4, validation = build_probe_video(args.language, lanes["youtube"])
        work = mp4.parent
        for credential_env in credential_names:
            client = ActionsZernioClient(
                config["base_url"],
                os.environ.get(credential_env, ""),
            )
            result = client.upload_temp_media(mp4)
            public_url = result.pop("public_url")
            storage_key = result.pop("storage_key")
            parsed = urlparse(public_url)
            uploads.append(
                {
                    "credential_env": credential_env,
                    "public_host": parsed.hostname or "",
                    "public_url_sha256": hashlib.sha256(public_url.encode("utf-8")).hexdigest(),
                    "storage_key_sha256": hashlib.sha256(storage_key.encode("utf-8")).hexdigest(),
                    **result,
                }
            )

    finally:
        if work is not None:
            remove_work_dir(work)

    temporary_media_removed = work is not None and not work.exists()
    if not temporary_media_removed:
        raise RuntimeError("Temporary media cleanup could not be verified")
    print(
        json.dumps(
            {
                "status": "SOCIAL_MEDIA_UPLOAD_PROBE_OK",
                "language": args.language,
                "market": lanes["social"]["market"],
                **account_validation,
                "generated_video_count": 1,
                "validation": validation,
                "media_upload_count": len(uploads),
                "media_uploads": uploads,
                "zernio_media_upload_performed": True,
                "social_post_created": False,
                "social_post_performed": False,
                "temporary_media_removed": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

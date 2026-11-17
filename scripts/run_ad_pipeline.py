from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.actions_youtube import ActionsYouTubeClient  # noqa: E402
from core.auto_uploader import BGM_DIR, OUT_DIR, _build_meta, plan_sets, render_html_to_png  # noqa: E402
from core.bgm_picker import DEFAULT_AUTO_VOLUME, pick as pick_bgm  # noqa: E402
from core.card_video import build_card_video  # noqa: E402


CONFIG_PATH = ROOT / "config" / "lanes.json"
ALLOWED_MODES = ("dry-run", "oauth-check", "private", "unlisted")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Proven JA/EN YouTube card-video pipeline")
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    parser.add_argument("--mode", choices=ALLOWED_MODES, default="dry-run")
    parser.add_argument("--max-videos", type=int, default=1)
    return parser.parse_args()


def load_lane(language: str) -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    lane = (config.get("languages") or {}).get(language)
    if not isinstance(lane, dict):
        raise RuntimeError(f"Lane configuration is missing: {language}")
    if lane.get("language") != language:
        raise RuntimeError("Lane language does not match the requested language")
    if not lane.get("expected_channel_id"):
        raise RuntimeError("Lane expected_channel_id is missing")
    return lane


def validate_video(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size < 1024:
        raise RuntimeError(f"Generated MP4 is missing or too small: {path.name}")
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe rejected the generated MP4")
    probe = json.loads(result.stdout)
    streams = probe.get("streams") or []
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    if len(videos) != 1:
        raise RuntimeError("Generated MP4 must contain exactly one video stream")
    video = videos[0]
    if int(video.get("width", 0)) != 1080 or int(video.get("height", 0)) != 1920:
        raise RuntimeError("Generated MP4 is not 1080x1920 portrait video")
    duration = float((probe.get("format") or {}).get("duration", 0))
    if duration < 5:
        raise RuntimeError("Generated MP4 duration is unexpectedly short")
    return {
        "bytes": path.stat().st_size,
        "duration_seconds": round(duration, 3),
        "video_codec": video.get("codec_name", ""),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "width": int(video["width"]),
        "height": int(video["height"]),
    }


def marketing_lines(require: bool) -> list[str]:
    cta = os.environ.get("AD_CTA", "").strip()
    link = os.environ.get("AD_LINK", "").strip()
    if require and (not cta or not link):
        raise RuntimeError("AD_CTA and AD_LINK must both be configured for an upload")
    if bool(cta) != bool(link):
        raise RuntimeError("AD_CTA and AD_LINK must be configured together")
    return [cta, link] if cta and link else []


def lane_card_check(cards: list[dict], language: str) -> None:
    for card in cards:
        card_lang = str(card.get("lang") or "ja").lower()
        if card_lang != language:
            raise RuntimeError(
                f"Language lane mismatch in generated card: expected={language} actual={card_lang}"
            )


def main() -> int:
    args = parse_args()
    if not 1 <= args.max_videos <= 4:
        raise RuntimeError("--max-videos must be between 1 and 4")

    lane = load_lane(args.language)
    upload_mode = args.mode in {"private", "unlisted"}
    now = datetime.now(ZoneInfo(str(lane.get("timezone") or "Asia/Tokyo")))
    day = now.date()
    logger = logging.getLogger("youtube-auto")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(logging.StreamHandler(sys.stdout))

    client = None
    identity = None
    if args.mode != "dry-run":
        client = ActionsYouTubeClient(str(lane["expected_channel_id"]))
        identity = client.check_identity()
        logger.info(
            "OAuth channel identity verified: lane=%s channel_id=%s",
            args.language,
            identity.channel_id,
        )
    if args.mode == "oauth-check":
        print(json.dumps({
            "status": "OAUTH_CHECK_OK",
            "language": args.language,
            "channel_id": identity.channel_id,
            "upload_performed": False,
        }, ensure_ascii=False))
        return 0

    cta_lines = marketing_lines(require=upload_mode)
    markers = [f"[youtube-auto:{args.language}:{day.isoformat()}:{slot:02d}]"
               for slot in range(1, args.max_videos + 1)]
    existing = client.existing_markers(markers) if client else set()

    sets = plan_sets(args.language, day, args.max_videos, {}, logger)
    if len(sets) != args.max_videos:
        raise RuntimeError(
            f"Planner returned {len(sets)} videos; expected {args.max_videos}. Upload stopped."
        )

    work = OUT_DIR / day.isoformat() / args.language
    generated: list[dict] = []
    uploaded: list[dict] = []
    try:
        for index, cards in enumerate(sets, start=1):
            marker = markers[index - 1]
            if marker in existing:
                logger.info("Idempotency marker already exists; slot %02d will not upload", index)
                continue
            lane_card_check(cards, args.language)
            pngs: list[str] = []
            for card_index, card in enumerate(cards, start=1):
                png = work / f"slot{index:02d}_card{card_index:02d}.png"
                png.parent.mkdir(parents=True, exist_ok=True)
                if not render_html_to_png(str(card["html"]), png, logger):
                    raise RuntimeError(f"HTML rendering failed for slot {index}")
                pngs.append(str(png))

            bgm = pick_bgm(BGM_DIR, seed=f"{day.isoformat()}:{args.language}:{index}", uniform=True)
            if not bgm:
                raise RuntimeError("No proven BGM asset is available")
            mp4 = work / f"youtube_auto_{args.language}_{day.isoformat()}_{index:02d}.mp4"
            if not build_card_video(
                pngs,
                str(mp4),
                bgm_path=bgm,
                volume=DEFAULT_AUTO_VOLUME,
                seconds_per_card=6.0,
                logger=logger,
            ):
                raise RuntimeError(f"Video encoding failed for slot {index}")
            validation = validate_video(mp4)
            meta = _build_meta(cards, args.language, False, logger, day=day)
            title = str(meta.get("title", "")).strip()
            description = str(meta.get("description", "")).strip()
            tags = [str(tag) for tag in (meta.get("tags") or [])]
            if not title or not description:
                raise RuntimeError("Generated title or description is empty")
            description = "\n\n".join(
                part for part in [description, *cta_lines, marker] if part
            )

            generated_item = {
                "slot": index,
                "content_ids": [str(card["id"]) for card in cards],
                "title": title,
                "validation": validation,
                "marker": marker,
            }
            generated.append(generated_item)
            logger.info(
                "Validated slot=%02d lang=%s bytes=%s duration=%ss audio=%s",
                index,
                args.language,
                validation["bytes"],
                validation["duration_seconds"],
                validation["has_audio"],
            )

            if upload_mode:
                result = client.upload(
                    video_path=mp4,
                    title=title,
                    description=description,
                    tags=tags,
                    privacy=args.mode,
                )
                uploaded.append({"slot": index, **result})
                logger.info(
                    "Upload verified: slot=%02d video_id=%s privacy=%s",
                    index,
                    result["video_id"],
                    result["privacy"],
                )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if not generated and not existing:
        raise RuntimeError("No video was generated")
    status = "DRY_RUN_OK" if args.mode == "dry-run" else "UPLOAD_OK"
    print(json.dumps({
        "status": status,
        "language": args.language,
        "mode": args.mode,
        "generated": generated,
        "uploaded": uploaded,
        "existing_markers": sorted(existing),
        "temporary_media_removed": not work.exists(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

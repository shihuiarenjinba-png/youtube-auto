"""Grounded application Campaign review cards and local video validation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bgm_picker import pick
from .card_video import build_card_video


class AppVideoHold(ValueError):
    """Fail-closed validation result for local advertising video generation."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    windows = [
        "C:/Windows/Fonts/YuGothB.ttc" if bold else "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/meiryob.ttc" if bold else "C:/Windows/Fonts/meiryo.ttc",
    ]
    linux = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in [*windows, *linux]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: Any, text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            box = draw.textbbox((0, 0), candidate, font=font)
            if current and box[2] - box[0] > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines


def _draw_wrapped(
    draw: Any,
    xy: tuple[int, int],
    text: str,
    font: Any,
    fill: tuple[int, int, int],
    width: int,
    spacing: int = 12,
) -> int:
    x, y = xy
    line_height = draw.textbbox((0, 0), "あAg", font=font)[3] + spacing
    for line in _wrap(draw, text, font, width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _paste_screenshot(canvas: Any, screenshot_path: Path, box: tuple[int, int, int, int]) -> None:
    from PIL import Image

    left, top, right, bottom = box
    target_w, target_h = right - left, bottom - top
    with Image.open(screenshot_path) as source:
        image = source.convert("RGB")
        image.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        x = left + (target_w - image.width) // 2
        y = top + (target_h - image.height) // 2
        canvas.paste(image, (x, y))


def verify_screenshots(campaign: dict[str, Any], root: Path) -> list[Path]:
    screenshots = campaign.get("screenshots") or []
    if len(screenshots) < 4:
        raise AppVideoHold("HOLD_APP_VIDEO_REQUIRES_FOUR_SCREENSHOTS")
    verified: list[Path] = []
    for item in screenshots:
        path = (root / str(item.get("path") or "")).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise AppVideoHold("HOLD_SCREENSHOT_OUTSIDE_REPOSITORY") from exc
        expected = str(item.get("sha256") or "")
        if not path.is_file() or len(expected) != 64 or sha256_file(path) != expected:
            raise AppVideoHold("HOLD_SCREENSHOT_HASH_MISMATCH")
        verified.append(path)
    return verified


def render_review_cards(
    campaign: dict[str, Any],
    content: dict[str, Any],
    *,
    root: Path,
    output_dir: Path,
) -> list[Path]:
    from PIL import Image, ImageDraw

    if content.get("campaign_id") != campaign.get("campaign_id"):
        raise AppVideoHold("HOLD_CAMPAIGN_CONTENT_ID_MISMATCH")
    if len(str(content.get("evidence_hash") or "")) != 64:
        raise AppVideoHold("HOLD_EVIDENCE_HASH_MISSING")
    screenshots = verify_screenshots(campaign, root)
    features = [str(value) for value in content.get("key_features") or []]
    if len(features) < 3:
        raise AppVideoHold("HOLD_INSUFFICIENT_SOURCE_EVIDENCE")

    output_dir.mkdir(parents=True, exist_ok=True)
    product = str(campaign["product_name"])
    summary = str(content.get("summary") or "")
    cta_url = str(content.get("cta_url") or "")
    end_card_details = "\n".join(
        str(value).strip()
        for value in (content.get("video_end_card_text"), cta_url)
        if str(value or "").strip()
    )
    cards = [
        ("Windows PCに記録", f"{summary}\n{features[0]}", screenshots[0]),
        ("毎日の習慣も", features[1], screenshots[1]),
        ("振り返りやすく", features[2], screenshots[2]),
        ("対応環境・入手先", end_card_details, screenshots[3]),
    ]

    rendered: list[Path] = []
    for index, (headline, body, screenshot) in enumerate(cards, start=1):
        canvas = Image.new("RGB", (1080, 1920), "#0B1220")
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((54, 48, 1026, 1872), radius=42, fill="#F7F8FC")
        draw.rounded_rectangle((54, 48, 1026, 310), radius=42, fill="#2459D3")
        draw.rectangle((54, 240, 1026, 310), fill="#2459D3")
        draw.text((92, 82), product, font=_font(48, bold=True), fill="white")
        disclosure_label = str(
            content.get("disclosure_label")
            or ("広告" if str(campaign.get("language") or "") == "ja" else "Ad")
        )
        disclosure_box = (842, 70, 988, 140)
        draw.rounded_rectangle(disclosure_box, radius=18, fill="#FFFFFF")
        draw.text((862, 82), disclosure_label, font=_font(30, bold=True), fill="#2459D3")
        _draw_wrapped(draw, (92, 164), headline, _font(64, bold=True), (255, 255, 255), 720, 10)
        # Keep the landscape app UI prominent instead of shrinking it inside a tall empty panel.
        draw.rounded_rectangle((92, 350, 988, 1000), radius=26, fill="#E8ECF5")
        _paste_screenshot(canvas, screenshot, (112, 374, 968, 976))
        _draw_wrapped(draw, (92, 1050), body, _font(38), (21, 31, 51), 890, 10)
        footer_disclosure = str(content.get("disclosure_statement") or disclosure_label)
        draw.text((92, 1810), f"{index}/4  •  {footer_disclosure}", font=_font(26), fill="#61708A")
        path = output_dir / f"card-{index:02d}.png"
        canvas.save(path, "PNG", optimize=True)
        rendered.append(path)
    return rendered


def probe_video(path: Path) -> dict[str, Any]:
    import imageio_ffmpeg

    try:
        reader = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgb24")
        metadata = next(reader)
        reader.close()
    except (OSError, RuntimeError, StopIteration) as exc:
        raise AppVideoHold("HOLD_VIDEO_PROBE_FAILED") from exc

    duration = float(metadata.get("duration") or 0)
    size = tuple(metadata.get("source_size") or metadata.get("size") or ())
    if metadata.get("codec") != "h264":
        raise AppVideoHold("HOLD_VIDEO_NOT_H264")
    if size != (1080, 1920):
        raise AppVideoHold("HOLD_VIDEO_NOT_1080X1920")
    if not metadata.get("audio_codec"):
        raise AppVideoHold("HOLD_VIDEO_AUDIO_MISSING")
    if not 10.0 <= duration <= 15.0:
        raise AppVideoHold("HOLD_VIDEO_DURATION_OUT_OF_RANGE")
    return {
        "codec": metadata["codec"],
        "width": size[0],
        "height": size[1],
        "audio_codec": metadata["audio_codec"],
        "duration_seconds": duration,
    }


def build_local_review_video(
    campaign: dict[str, Any],
    content: dict[str, Any],
    *,
    root: Path,
    output_path: Path,
    cards_dir: Path,
) -> dict[str, Any]:
    cards = render_review_cards(campaign, content, root=root, output_dir=cards_dir)
    bgm = pick(root / "assets" / "bgm", seed=str(content["evidence_hash"]))
    if not bgm:
        raise AppVideoHold("HOLD_BGM_NOT_AVAILABLE")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_card_video(
        [str(path) for path in cards],
        str(output_path),
        bgm_path=bgm,
        volume=0.14,
        seconds_per_card=3.0,
        effect="crossfade",
        fps=30,
    )
    validation = probe_video(output_path)
    validation.update({
        "video_path": str(output_path),
        "video_sha256": sha256_file(output_path),
        "bgm_name": Path(bgm).name,
        "bgm_path": Path(bgm).resolve().relative_to(root.resolve()).as_posix(),
        "card_count": len(cards),
    })
    return validation



def write_video_review_bundle(
    campaign: dict[str, Any],
    content: dict[str, Any],
    *,
    root: Path,
    cards_dir: Path,
    video_path: Path,
    evidence_dir: Path,
    validation: dict[str, Any],
) -> Path:
    """Copy the exact generated video and its source assets into a reviewable bundle."""
    if content.get("campaign_id") != campaign.get("campaign_id"):
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_CAMPAIGN_MISMATCH")

    screenshots = verify_screenshots(campaign, root)
    cards = sorted(cards_dir.glob("card-*.png"))
    if len(screenshots) < 4 or len(cards) != 4:
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_EXPECTS_FOUR_CARDS")
    if not video_path.is_file() or video_path.stat().st_size < 1024:
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_VIDEO_MISSING")
    actual_video_sha = sha256_file(video_path)
    if actual_video_sha != str(validation.get("video_sha256") or ""):
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_VIDEO_HASH_MISMATCH")

    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_DIRECTORY_NOT_EMPTY")

    evidence_dir.mkdir(parents=True, exist_ok=True)
    source_dir = evidence_dir / "source-screenshots"
    card_dir = evidence_dir / "rendered-cards"
    audio_dir = evidence_dir / "audio"
    source_dir.mkdir()
    card_dir.mkdir()
    audio_dir.mkdir()

    source_assets: list[dict[str, Any]] = []
    for index, (item, source_path) in enumerate(zip(campaign.get("screenshots") or [], screenshots)):
        expected_sha = str(item.get("sha256") or "")
        actual_sha = sha256_file(source_path)
        if actual_sha != expected_sha:
            raise AppVideoHold("HOLD_REVIEW_BUNDLE_SOURCE_HASH_MISMATCH")
        copied_name = f"source-{index + 1:02d}{source_path.suffix.lower()}"
        shutil.copy2(source_path, source_dir / copied_name)
        source_assets.append({
            "campaign_path": str(item.get("path") or ""),
            "sha256": actual_sha,
            "bundle_path": f"source-screenshots/{copied_name}",
            "used_in_video": index < 4,
            "scene_number": index + 1 if index < 4 else None,
        })

    rendered_cards: list[dict[str, Any]] = []
    for index, card_path in enumerate(cards, start=1):
        copied_name = f"card-{index:02d}.png"
        shutil.copy2(card_path, card_dir / copied_name)
        rendered_cards.append({
            "bundle_path": f"rendered-cards/{copied_name}",
            "sha256": sha256_file(card_path),
            "source_campaign_path": str((campaign.get("screenshots") or [])[index - 1]["path"]),
        })

    video_name = "daymark-ai-review.mp4"
    shutil.copy2(video_path, evidence_dir / video_name)

    bgm_name = str(validation.get("bgm_name") or "")
    bgm_relative_path = str(validation.get("bgm_path") or "")
    if not bgm_name or not bgm_relative_path:
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_BGM_PATH_MISSING")
    bgm_path = (root / bgm_relative_path).resolve()
    try:
        bgm_path.relative_to((root / "assets" / "bgm").resolve())
    except ValueError as exc:
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_BGM_OUTSIDE_ASSET_ROOT") from exc
    if not bgm_path.is_file() or bgm_path.name != bgm_name:
        raise AppVideoHold("HOLD_REVIEW_BUNDLE_BGM_MISSING")
    shutil.copy2(bgm_path, audio_dir / bgm_path.name)

    evidence = {
        "schema_version": 1,
        "review_status": "REVIEW_REQUIRED_NOT_PUBLISHED_BY_PREVIEW_JOB",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.environ.get("GITHUB_SHA") or None,
        "source_ref": os.environ.get("GITHUB_REF") or None,
        "campaign_id": str(campaign.get("campaign_id") or ""),
        "app_id": str(campaign.get("app_id") or ""),
        "product_name": str(campaign.get("product_name") or ""),
        "generated_from_source_hash": str(content.get("generated_from_source_hash") or ""),
        "evidence_hash": str(content.get("evidence_hash") or ""),
        "generation": {
            "mode": "screenshot_cards_crossfade_with_local_bgm",
            "image_generation_api_used": False,
            "voice_generation_api_used": False,
            "audio_mode": "local_bgm",
        },
        "source_assets": source_assets,
        "rendered_cards": rendered_cards,
        "audio": {
            "bundle_path": f"audio/{bgm_path.name}",
            "sha256": sha256_file(bgm_path),
        },
        "video": {
            "bundle_path": video_name,
            "sha256": actual_video_sha,
            "codec": validation.get("codec"),
            "width": validation.get("width"),
            "height": validation.get("height"),
            "audio_codec": validation.get("audio_codec"),
            "duration_seconds": validation.get("duration_seconds"),
        },
        "publication": {
            "performed": False,
            "reason": "This bundle is a preview artifact only. Publishing is a separate approved operation.",
        },
    }
    evidence_path = evidence_dir / "generation-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return evidence_path

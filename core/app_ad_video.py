"""Grounded application Campaign review cards and local video validation."""

from __future__ import annotations

import hashlib
import json
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
        for value in (
            content.get("compatibility_notice"),
            content.get("local_ai_notice"),
            content.get("ai_independence_notice"),
            content.get("store_link_notice"),
            cta_url,
        )
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
        draw.rounded_rectangle((92, 350, 988, 1330), radius=26, fill="#E8ECF5")
        _paste_screenshot(canvas, screenshot, (116, 374, 964, 1306))
        _draw_wrapped(draw, (92, 1390), body, _font(38), (21, 31, 51), 890, 10)
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
        "card_count": len(cards),
    })
    return validation

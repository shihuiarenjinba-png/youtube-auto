"""
動画合成エンジン (moviepy 2.x API)
==================================
- 等間隔自動配分 (x/y)
- エフェクト (YouTube Shorts/縦動画で定番の手法を網羅):
    zoom      : Ken Burns ゆっくりズーム
    slide     : 画像を横にパン (流れるスライド)
    cut       : 動画を尺に合わせて早送りカット
    blur_fill : 切り抜かず背景をぼかして余白を埋める (縦動画定番)
    punch     : クリップ冒頭で一瞬グッと寄るパンチイン
    shake     : 手ブレ風シェイクで勢いを出す
    crossfade : クリップ間をディゾルブ (溶暗転換)
    flash     : クリップ間に白フラッシュ転換
- 9:16 / 16:9 / 1:1 アスペクト対応
- 素材ごとに個別のトリミング (start, end) を受け取れる
- Pillow ベースのテキストオーバーレイ (ImageMagick 不要)
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Dict, Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from moviepy import (
    ImageClip,
    VideoFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
from moviepy.video.fx import (
    Resize, Crop, MultiplySpeed, CrossFadeIn, CrossFadeOut, MultiplyColor,
)

EffectMode = Literal[
    "zoom", "slide", "cut", "blur_fill", "punch", "shake", "crossfade", "flash"
]

# 全エフェクトの選択肢 (内部値)
EFFECT_CHOICES: List[str] = [
    "zoom", "slide", "cut", "blur_fill", "punch", "shake", "crossfade", "flash"
]

# UI 表示用の分かりやすい日本語ラベル (表示名, 内部値)
EFFECT_LABELS: List[Tuple[str, str]] = [
    ("🔍 ズーム（ゆっくり寄る）", "zoom"),
    ("↔️ 横スライド（流す）", "slide"),
    ("✂️ 早送りカット", "cut"),
    ("🌫️ ぼかし背景（余白を埋める）", "blur_fill"),
    ("👊 パンチイン（一気に寄る）", "punch"),
    ("📳 手ブレ（揺らす）", "shake"),
    ("🌗 クロスフェード（溶けて切替）", "crossfade"),
    ("⚡ 白フラッシュ切替", "flash"),
]

# クリップ間転換系 (連結方法を変える)
TRANSITION_EFFECTS = {"crossfade", "flash"}

# クリップ内アニメーション系 (1枚ずつに適用)
ANIM_EFFECTS = {"zoom", "punch", "shake"}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class VideoComposer:
    def __init__(self, total_seconds: float, aspect: str = "9:16", fps: int = 30):
        self.total_seconds = float(total_seconds)
        self.aspect = aspect
        self.fps = fps
        self.width, self.height = self._resolve_size(aspect)

    @staticmethod
    def _resolve_size(aspect: str) -> Tuple[int, int]:
        return {
            "9:16": (1080, 1920),
            "16:9": (1920, 1080),
            "1:1": (1080, 1080),
        }.get(aspect, (1080, 1920))

    # -----------------------------------------------------------------
    # メイン
    # -----------------------------------------------------------------
    def compose(
        self,
        materials: List[Dict[str, Any]],
        effect: EffectMode,
        overlay_text: str = "",
    ):
        if not materials:
            raise ValueError("素材が0件です")

        n = len(materials)
        fade = 0.4  # 転換の重なり/フラッシュ長

        # crossfade はクリップが重なる分、総尺が縮むので1枚あたりを延ばして補正
        if effect == "crossfade" and n > 1:
            per_clip_duration = (self.total_seconds + (n - 1) * fade) / n
        else:
            per_clip_duration = self.total_seconds / n

        clips = []
        for m in materials:
            path = m["path"]
            ts = m.get("trim_start")
            te = m.get("trim_end")
            clip = self._build_clip(path, per_clip_duration, effect, ts, te)
            clips.append(clip)

        # 連結 (転換エフェクトごとに方法を変える)
        if effect == "crossfade" and n > 1:
            clips = [clips[0]] + [c.with_effects([CrossFadeIn(fade)]) for c in clips[1:]]
            video = concatenate_videoclips(clips, method="compose", padding=-fade)
        else:
            video = concatenate_videoclips(clips, method="compose")
            if effect == "flash" and n > 1:
                video = self._apply_flash(video, per_clip_duration, n, fade)

        if overlay_text:
            overlay = self._make_text_overlay(overlay_text, video.duration)
            video = CompositeVideoClip([video, overlay], size=(self.width, self.height))

        return video

    # -----------------------------------------------------------------
    # クリップ生成
    # -----------------------------------------------------------------
    def _build_clip(
        self,
        path: str,
        duration: float,
        effect: EffectMode,
        trim_start: Optional[float],
        trim_end: Optional[float],
    ):
        ext = Path(path).suffix.lower()
        if ext in IMAGE_EXTS:
            return self._image_clip(path, duration, effect)
        return self._video_clip(path, duration, effect, trim_start, trim_end)

    def _image_clip(self, path: str, duration: float, effect: EffectMode):
        if effect == "slide":
            return self._apply_slide(path, duration)
        if effect == "blur_fill":
            base = ImageClip(path).with_duration(duration)
            return self._blur_fill(base, duration)
        clip = ImageClip(path).with_duration(duration)
        clip = self._fit_canvas(clip)
        return self._animate(clip, effect, duration)

    def _video_clip(
        self,
        path: str,
        duration: float,
        effect: EffectMode,
        trim_start: Optional[float],
        trim_end: Optional[float],
    ):
        raw = VideoFileClip(path).without_audio()

        if trim_start is not None or trim_end is not None:
            s = max(0.0, float(trim_start or 0.0))
            e = float(trim_end) if trim_end is not None else raw.duration
            e = min(e, raw.duration)
            if e <= s:
                e = min(raw.duration, s + 0.1)
            raw = raw.subclipped(s, e)

        if effect == "cut":
            speed_factor = max(raw.duration / duration, 0.01)
            clip = raw.with_effects([MultiplySpeed(factor=speed_factor)])
            # 速度後の長さがズレた場合の安全カット
            if clip.duration > duration:
                clip = clip.subclipped(0, duration)
        else:
            if raw.duration >= duration:
                clip = raw.subclipped(0, duration)
            else:
                loops = int(np.ceil(duration / raw.duration))
                clip = concatenate_videoclips([raw] * loops).subclipped(0, duration)

        if effect == "blur_fill":
            return self._blur_fill(clip, duration)

        clip = self._fit_canvas(clip)
        return self._animate(clip, effect, duration)

    # -----------------------------------------------------------------
    # クリップ内アニメーションの振り分け
    # -----------------------------------------------------------------
    def _animate(self, clip, effect: EffectMode, duration: float):
        if effect == "zoom":
            return self._apply_zoom(clip, duration)
        if effect == "punch":
            return self._apply_punch(clip, duration)
        if effect == "shake":
            return self._apply_shake(clip, duration)
        return clip

    # -----------------------------------------------------------------
    # キャンバスフィット
    # -----------------------------------------------------------------
    def _fit_canvas(self, clip):
        cw, ch = clip.size
        target_ratio = self.width / self.height
        current_ratio = cw / ch

        if abs(current_ratio - target_ratio) > 1e-3:
            if current_ratio > target_ratio:
                new_w = int(ch * target_ratio)
                x1 = (cw - new_w) // 2
                clip = clip.with_effects([Crop(x1=x1, x2=x1 + new_w)])
            else:
                new_h = int(cw / target_ratio)
                y1 = (ch - new_h) // 2
                clip = clip.with_effects([Crop(y1=y1, y2=y1 + new_h)])

        clip = clip.with_effects([Resize(new_size=(self.width, self.height))])
        return clip

    # -----------------------------------------------------------------
    # エフェクト
    # -----------------------------------------------------------------
    def _apply_zoom(self, clip, duration: float):
        """Ken Burns: ゆっくり1.0→1.18倍にズーム"""
        def zoom_func(t):
            return 1.0 + 0.18 * (t / max(duration, 1e-6))
        return clip.with_effects([Resize(new_size=zoom_func)])

    def _apply_slide(self, image_path: str, duration: float):
        """画像をキャンバス縦に合わせて、横方向にゆっくりスクロール"""
        img = Image.open(image_path).convert("RGB")
        iw, ih = img.size

        scale = self.height / ih
        new_w = max(int(iw * scale), self.width + 1)
        new_h = self.height
        img_resized = img.resize((new_w, new_h), Image.LANCZOS)
        arr = np.array(img_resized)

        base = ImageClip(arr).with_duration(duration)
        max_shift = new_w - self.width

        def pos_func(t):
            progress = t / max(duration, 1e-6)
            x = -int(max_shift * progress)
            return (x, 0)

        return CompositeVideoClip(
            [base.with_position(pos_func)],
            size=(self.width, self.height),
        ).with_duration(duration)

    def _apply_punch(self, clip, duration: float):
        """パンチイン: 冒頭で1.15倍からグッと1.0へ素早く収束 (勢いのある入り)"""
        def zoom_func(t):
            return 1.0 + 0.15 * math.exp(-t / 0.18)
        return clip.with_effects([Resize(new_size=zoom_func)])

    def _apply_shake(self, clip, duration: float):
        """手ブレ風シェイク: わずかに拡大して位置を高速振動させる"""
        big = clip.with_effects([Resize(1.06)])
        bw, bh = big.size
        amp = max(6, int(self.width * 0.008))

        def pos_func(t):
            dx = amp * math.sin(t * 37.0) + 0.5 * amp * math.sin(t * 91.0)
            dy = amp * math.cos(t * 43.0) + 0.5 * amp * math.cos(t * 71.0)
            x = (self.width - bw) / 2 + dx
            y = (self.height - bh) / 2 + dy
            return (x, y)

        return CompositeVideoClip(
            [big.with_position(pos_func)],
            size=(self.width, self.height),
        ).with_duration(duration)

    def _fit_contain(self, clip):
        """キャンバス内に収まるよう余白を残して縮小 (切り抜かない)"""
        cw, ch = clip.size
        scale = min(self.width / cw, self.height / ch)
        new_w = max(1, int(cw * scale))
        new_h = max(1, int(ch * scale))
        return clip.with_effects([Resize(new_size=(new_w, new_h))])

    def _cheap_blur(self, clip):
        """縮小→拡大の補間でぼかしを擬似再現 (フレームごとに高速)"""
        small = (max(1, self.width // 24), max(1, self.height // 24))
        return clip.with_effects([
            Resize(new_size=small),
            Resize(new_size=(self.width, self.height)),
        ])

    def _blur_fill(self, clip, duration: float):
        """切り抜かず、背景をぼかして余白を埋める (縦動画の定番レイアウト)"""
        bg = self._fit_canvas(clip)           # キャンバス全面を覆う (cover)
        bg = self._cheap_blur(bg)
        bg = bg.with_effects([MultiplyColor(0.6)])  # 主役を引き立てるため暗く
        fg = self._fit_contain(clip)          # 主役は全体が見えるように収める
        return CompositeVideoClip(
            [bg.with_position("center"), fg.with_position("center")],
            size=(self.width, self.height),
        ).with_duration(duration)

    def _apply_flash(self, video, per_clip: float, n: int, fade: float):
        """連結済み動画のクリップ境界に白フラッシュを重ねる"""
        layers = [video]
        flash_dur = max(0.12, fade * 0.4)
        for i in range(1, n):
            t = i * per_clip - flash_dur / 2
            if t < 0:
                t = 0.0
            white = (
                ImageClip(
                    np.full((self.height, self.width, 3), 255, dtype=np.uint8)
                )
                .with_duration(flash_dur)
                .with_start(t)
                .with_effects([CrossFadeIn(flash_dur * 0.4), CrossFadeOut(flash_dur * 0.6)])
            )
            layers.append(white)
        return CompositeVideoClip(layers, size=(self.width, self.height)).with_duration(
            video.duration
        )

    # -----------------------------------------------------------------
    # テキストオーバーレイ (Pillow)
    # -----------------------------------------------------------------
    def _make_text_overlay(self, text: str, duration: float):
        size = (self.width, self.height)
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font = None
        for path, sz in [
            ("C:/Windows/Fonts/seguiemj.ttf", 90),
            ("C:/Windows/Fonts/YuGothB.ttc", 90),
            ("C:/Windows/Fonts/meiryob.ttc", 90),
            ("C:/Windows/Fonts/arialbd.ttf", 90),
        ]:
            try:
                font = ImageFont.truetype(path, sz)
                break
            except OSError:
                continue
        if font is None:
            font = ImageFont.load_default()

        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw, _ = draw.textsize(text, font=font)

        x = (size[0] - tw) // 2
        y = int(size[1] * 0.08)

        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 230))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

        arr = np.array(img)
        return ImageClip(arr, transparent=True).with_duration(duration)

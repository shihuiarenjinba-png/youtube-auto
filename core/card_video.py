# -*- coding: utf-8 -*-
"""Grounded image cards to short-form video with narration and optional BGM."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

DEFAULT_SECONDS_PER_CARD = 6.0


def build_card_video(
    png_paths: List[str],
    out_mp4: str,
    bgm_path: Optional[str] = None,
    volume: float = 0.18,
    seconds_per_card: float = DEFAULT_SECONDS_PER_CARD,
    effect: str = "crossfade",
    fps: int = 30,
    logger=None,
    narration_path: Optional[str] = None,
    narration_volume: float = 1.0,
) -> bool:
    """Render portrait cards; mix narration clearly above optional quiet BGM."""
    from core.video_composer import VideoComposer

    pngs = [str(p) for p in png_paths if Path(p).exists()]
    if not pngs:
        raise ValueError("画像が0件です")
    if narration_path and not Path(narration_path).is_file():
        raise ValueError("HOLD_AD_NARRATION_FILE_MISSING")

    n = len(pngs)
    eff = effect if n > 1 else "zoom"
    total = max(seconds_per_card, seconds_per_card * n)
    vc = VideoComposer(total_seconds=total, aspect="9:16", fps=fps)
    video = vc.compose([{"path": p} for p in pngs], effect=eff)

    audio_clips = []
    has_audio = False
    try:
        if narration_path:
            from moviepy import AudioFileClip
            narration = AudioFileClip(str(narration_path))
            if float(narration.duration or 0) > float(video.duration) + 0.25:
                narration.close()
                raise ValueError("HOLD_AD_NARRATION_EXCEEDS_VIDEO_DURATION")
            audio_clips.append(narration.with_volume_scaled(float(narration_volume)))
            has_audio = True

        if bgm_path and Path(bgm_path).exists():
            try:
                from core.audio_looper import AudioLooper
                looper = AudioLooper(target_duration=video.duration)
                bgm_audio = looper.loop_single(str(bgm_path), volume=float(volume))
                audio_clips.append(bgm_audio)
                has_audio = True
                if logger:
                    logger.info(f"BGMを低音量でミックス: {Path(bgm_path).name} (vol={volume})")
            except Exception as exc:
                if logger:
                    logger.warning(f"BGM付与に失敗（ナレーションは維持）: {exc}")

        if audio_clips:
            from moviepy import CompositeAudioClip
            mixed_audio = CompositeAudioClip(audio_clips).with_duration(video.duration)
            video = video.with_audio(mixed_audio)

        Path(out_mp4).parent.mkdir(parents=True, exist_ok=True)
        kwargs = dict(
            fps=fps, codec="libx264", preset="veryfast",
            threads=4, logger=None, audio=has_audio,
        )
        if has_audio:
            kwargs["audio_codec"] = "aac"
        video.write_videofile(str(out_mp4), **kwargs)
    finally:
        for clip in audio_clips:
            try:
                clip.close()
            except Exception:
                pass
        try:
            video.close()
        except Exception:
            pass
    return Path(out_mp4).exists()

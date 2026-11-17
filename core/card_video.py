# -*- coding: utf-8 -*-
"""
カード → ショート動画（BGM付き・スライドショー対応）
====================================================
RAGの診断カード（PNG）を1枚または数枚まとめて、9:16のショート動画にする
共通ビルダー。自動アップロードと手動アップロード(RAGタブ)の両方から使う。

- 1枚 → ゆっくりズーム（Ken Burns）
- 複数枚 → クロスフェードで連結したスライドショー
- BGM を指定すると、尺に合わせてシームレスループ＋うっすら音量でミックス
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

DEFAULT_SECONDS_PER_CARD = 6.0


def build_card_video(png_paths: List[str],
                     out_mp4: str,
                     bgm_path: Optional[str] = None,
                     volume: float = 0.18,
                     seconds_per_card: float = DEFAULT_SECONDS_PER_CARD,
                     effect: str = "crossfade",
                     fps: int = 30,
                     logger=None) -> bool:
    """カードPNG群を1本のショートmp4に。BGM任意。成功で True。"""
    from core.video_composer import VideoComposer

    pngs = [str(p) for p in png_paths if Path(p).exists()]
    if not pngs:
        raise ValueError("画像が0件です")

    n = len(pngs)
    eff = effect if n > 1 else "zoom"        # 1枚はズーム演出
    total = max(seconds_per_card, seconds_per_card * n)

    vc = VideoComposer(total_seconds=total, aspect="9:16", fps=fps)
    video = vc.compose([{"path": p} for p in pngs], effect=eff)

    has_audio = False
    if bgm_path and Path(bgm_path).exists():
        try:
            from core.audio_looper import AudioLooper
            looper = AudioLooper(target_duration=video.duration)
            audio = looper.loop_single(str(bgm_path), volume=float(volume))
            video = video.with_audio(audio)
            has_audio = True
            if logger:
                logger.info(f"BGMをミックス: {Path(bgm_path).name} (vol={volume})")
        except Exception as e:
            if logger:
                logger.warning(f"BGM付与に失敗（無音で続行）: {e}")

    Path(out_mp4).parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(fps=fps, codec="libx264", preset="veryfast",
                  threads=4, logger=None, audio=has_audio)
    if has_audio:
        kwargs["audio_codec"] = "aac"
    video.write_videofile(str(out_mp4), **kwargs)
    return Path(out_mp4).exists()

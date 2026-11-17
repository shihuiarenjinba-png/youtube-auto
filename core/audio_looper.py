"""
BGM処理 (moviepy 2.x API)
=========================
- クロスフェード付きシームレスループ
- 任意尺へのフィット
- 音量調整
- 複数BGMの順次連結 (UI上で複数アップ→繋ぎ)
"""

from __future__ import annotations

from typing import List, Optional
import numpy as np

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    concatenate_audioclips,
)
from moviepy.audio.fx import (
    MultiplyVolume,
    AudioFadeIn,
    AudioFadeOut,
)


class AudioLooper:
    def __init__(self, target_duration: float):
        self.target_duration = float(target_duration)

    # -----------------------------------------------------------------
    # 単一BGMをシームレスループで尺合わせ
    # -----------------------------------------------------------------
    def loop_single(
        self,
        bgm_path: str,
        volume: float = 0.7,
        crossfade_sec: float = 0.6,
        fade_in: float = 0.4,
        fade_out: float = 0.8,
    ):
        bgm = AudioFileClip(bgm_path)

        if bgm.duration >= self.target_duration:
            out = bgm.subclipped(0, self.target_duration)
        else:
            out = self._seamless_loop(bgm, crossfade_sec)

        out = out.with_effects([
            MultiplyVolume(factor=volume),
            AudioFadeIn(duration=fade_in),
            AudioFadeOut(duration=fade_out),
        ])
        return out

    def _seamless_loop(self, bgm, crossfade_sec: float):
        """末尾と先頭をクロスフェードさせて自然ループを作る"""
        base_dur = bgm.duration
        step = max(base_dur - crossfade_sec, 0.1)
        loops_needed = int(np.ceil(self.target_duration / step)) + 1

        layers = [bgm]
        cursor = base_dur - crossfade_sec
        for i in range(1, loops_needed):
            next_clip = bgm.with_effects([AudioFadeIn(duration=crossfade_sec)]).with_start(cursor)
            layers.append(next_clip)
            cursor += base_dur - crossfade_sec
            if cursor >= self.target_duration:
                break

        composed = CompositeAudioClip(layers)
        # CompositeAudioClip では duration が自動算出されないことがあるため明示
        composed = composed.with_duration(min(self.target_duration, cursor + crossfade_sec))
        # 必要尺ぴったりに揃える
        if composed.duration > self.target_duration:
            composed = composed.subclipped(0, self.target_duration)
        return composed

    # -----------------------------------------------------------------
    # 複数BGMを順に繋ぎ、足りなければ最後のをループ
    # -----------------------------------------------------------------
    def chain_then_loop(
        self,
        bgm_paths: List[str],
        volume: float = 0.7,
        crossfade_sec: float = 0.6,
    ):
        if not bgm_paths:
            return None
        if len(bgm_paths) == 1:
            return self.loop_single(bgm_paths[0], volume=volume, crossfade_sec=crossfade_sec)

        clips = [AudioFileClip(p) for p in bgm_paths]
        total = sum(c.duration for c in clips)

        if total >= self.target_duration:
            joined = concatenate_audioclips(clips).subclipped(0, self.target_duration)
        else:
            joined_head = concatenate_audioclips(clips)
            remain = self.target_duration - joined_head.duration
            tail_looper = AudioLooper(target_duration=remain + crossfade_sec)
            tail = tail_looper._seamless_loop(clips[-1], crossfade_sec).subclipped(0, remain)
            joined = concatenate_audioclips([joined_head, tail])

        joined = joined.with_effects([
            MultiplyVolume(factor=volume),
            AudioFadeIn(duration=0.4),
            AudioFadeOut(duration=0.8),
        ])
        return joined

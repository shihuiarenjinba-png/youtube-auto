# -*- coding: utf-8 -*-
"""
BGM 重み付きピッカー（正規分布で“定番”がよく当たる）
====================================================
自動アップロードでBGMを選ぶときの方針:

  - 基本はランダム（毎回ちがう）。ただし完全な一様乱数ではなく、
    「幅広く・統計的によく使われるスタイル」が当たりやすいように
    “人気ランク”に対して正規分布（ガウシアン）の重みをかける。
    → 定番(lo-fi/ピアノ)が高確率、ニッチ(アンビエント等)は時々。
  - 自動実行では日付シードで決定的（同じ日なら同じ選曲＝再現性）。
  - 音量は既定で“うっすら”（DEFAULT_AUTO_VOLUME）。

楽曲ファイルは assets/bgm/music/ を第一候補にする（環境音/ノイズではなく
ちゃんと聴ける曲）。ユーザーが custom 等に足した曲も拾える。
"""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path
from typing import List, Optional, Sequence

SUPPORTED_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

# うっすら背景で流す既定音量（メイン動画タブの既定0.7より大幅に控えめ）
DEFAULT_AUTO_VOLUME = 0.18

# よく使われる順（前ほど“定番”＝当たりやすい）。assets/bgm/music の自作曲。
POPULARITY = [
    "lofi_warm",       # 王道lo-fi（一番汎用・人気）
    "piano_calm",      # 静かなピアノ
    "gentle_morning",  # 明るめの定番
    "night_lofi",      # 夜lo-fi
    "soft_hope",       # 前向き
    "ambient_dream",   # アンビエント（ニッチ）
]

# 正規分布の広がり。小さいほど定番に集中、大きいほど均一寄り。
SIGMA = 1.6


def _rank(stem: str) -> int:
    if stem in POPULARITY:
        return POPULARITY.index(stem)
    return len(POPULARITY)  # 未知（custom等）は末尾扱い＝低確率


def list_candidates(bgm_root: Path,
                    genres: Sequence[str] = ("music",)) -> List[Path]:
    """候補となるBGMファイル一覧（指定ジャンルのみ）。"""
    root = Path(bgm_root)
    out: List[Path] = []
    for g in genres:
        gdir = root / g
        if gdir.exists():
            out += sorted(p for p in gdir.iterdir()
                          if p.is_file() and p.suffix.lower() in SUPPORTED_EXT)
    return out


def _weights(paths: Sequence[Path]) -> List[float]:
    """人気ランクに正規分布をかけた重み（合計1に正規化）。"""
    raw = [math.exp(-(_rank(p.stem) ** 2) / (2.0 * SIGMA * SIGMA)) for p in paths]
    s = sum(raw) or 1.0
    return [w / s for w in raw]


def pick(bgm_root: Path,
         seed: Optional[str] = None,
         genres: Sequence[str] = ("music",),
         fallback_genres: Sequence[str] = ("relaxing", "ambient", "nature"),
         uniform: bool = False) -> Optional[str]:
    """BGMを1曲選ぶ。seedを渡すと決定的（自動実行向け）。

    music ジャンルに曲が無ければ fallback_genres も探す。1曲も無ければ None。
    uniform=True なら人気重みを無視して全曲“等確率”で選ぶ（偏り無し）。
    """
    paths = list_candidates(bgm_root, genres)
    if not paths:
        paths = list_candidates(bgm_root, fallback_genres)
    if not paths:
        return None

    if seed is not None:
        s = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % (2 ** 32)
        rnd = random.Random(s)
    else:
        rnd = random.Random()

    if uniform:
        # 全曲一様抽選（どの曲も等確率＝偏らない）
        return str(rnd.choice(paths))

    weights = _weights(paths)
    chosen = rnd.choices(paths, weights=weights, k=1)[0]
    return str(chosen)


def ensure_music(bgm_root: Path) -> int:
    """楽曲BGMが無ければ生成する。生成した曲数を返す（あれば0）。"""
    paths = list_candidates(Path(bgm_root), ("music",))
    if paths:
        return 0
    try:
        from core.music_bgm import generate_all_music
        return len(generate_all_music(Path(bgm_root), overwrite=False))
    except Exception:
        return 0

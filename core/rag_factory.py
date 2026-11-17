# -*- coding: utf-8 -*-
"""
RAGカード・ファクトリ（核ランダム → ルール生成）
====================================================
設計方針（ユーザー要望）:

  「フォーマット（カード）はそのままに、“核”をランダムに選んで、そこから
   一定の法則（ルール）で文章を生成して中身を差し替える」

  ✗ 旧: 全120枚を焼いた在庫(examples.jsonl)から、ランダムに1枚“選ぶ”
  ◯ 新: 核(=どの型ペアか)をランダムに“選び”、その核から毎回ルールで生成する

ランダム性は「核(入力)」の側にあり、出来上がる文章は核の決定的な関数。
自動アップは日付シードで決定的（同じ日＝同じ核＝再現性）。手動は全核から自由に。

いまは MBTI相性(mbti_compat)を対象に実装。他ジャンル(干支/星座/誕生数)は
“核=単一の対象(動物/星座/数)”でもともと小さな固定集合なので、どれを選ぶか自体が
すでに核選択になっている（必要なら同じ仕組みに寄せられる）。
"""
from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
# tools/rag_starter をインポート可能に（gen_mbti_compat の生成ルールを再利用）
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _seeded_rng(seed: str | None) -> random.Random:
    if seed:
        s = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % (2 ** 32)
        return random.Random(s)
    return random.Random()


def _strip_compat_prefix(rid: str) -> str:
    """'compat_en_INTJ_ENFP' / 'compat_INTJ_ENFP' → 'INTJ_ENFP'。"""
    for pre in ("compat_en_", "compat_"):
        if rid.startswith(pre):
            return rid[len(pre):]
    return rid


def pick_compat_cores(lang: str,
                      seed: str | None = None,
                      n: int = 12,
                      min_score: int = 0,
                      exclude_codes: Sequence[str] = ()) -> List[Tuple[str, str, str, int]]:
    """“核”(型ペア)をランダムに選ぶ。戻り値は (ti, tj, code, score) のリスト。

    - min_score: 品質ゲート。スコアがこの値未満の核は母集団から外す。
    - exclude_codes: 直近で使った核(code)を避ける。
    - seed: 渡すと決定的（自動実行向け／同じ日なら同じ核）。
    """
    from tools.rag_starter import gen_mbti_compat as gmc

    curated = gmc.curated_map(lang)
    exclude = set(exclude_codes)
    pool: List[Tuple[str, str, str, int]] = []
    for ti, tj in gmc.all_cores():
        _, code = gmc.pair_data(ti, tj, lang, curated)
        if code in exclude:
            continue
        sc = gmc.score_for_core(ti, tj, lang, curated)
        if sc < min_score:
            continue
        pool.append((ti, tj, code, sc))

    rng = _seeded_rng(seed)
    rng.shuffle(pool)
    return pool[:max(0, n)]


def generate_compat_card(core: Tuple[str, str, str, int], lang: str) -> Dict[str, Any]:
    """核 → カードを“その場で”生成（HTMLを書き出し、レコードを返す）。

    返すレコードは examples.jsonl と同じ形なので、auto_uploader / card_video が
    そのまま使える（html は data/rag/ からの相対パス）。
    """
    from tools.rag_starter import gen_mbti_compat as gmc

    ti, tj, _code, _sc = core
    return gmc.write_card(ti, tj, lang)


def make_compat_candidates(lang: str,
                           seed: str | None,
                           n: int,
                           min_score: int = 0,
                           recent_ids: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """自動アップ用: 核をランダムに選んで n 枚ぶんのカードを生成して返す。

    recent_ids（直近アップ済みid）から避けるべき核codeを割り出して除外する。
    """
    exclude = {_strip_compat_prefix(r) for r in recent_ids
               if str(r).startswith("compat")}
    cores = pick_compat_cores(lang, seed=seed, n=n,
                              min_score=min_score, exclude_codes=exclude)
    return [generate_compat_card(c, lang) for c in cores]


# =====================================================================
# MBTIランキング: “核=並び順”をランダムに作って毎回生成する（同様の方針）
# ---------------------------------------------------------------------
# ランキングは在庫から選ぶと“同じ並びがキャッシュ”されてしまうため、テーマと
# 並び順をその場でランダムに決めて生成する。重みつきテーマでも乱数ゆらぎで毎回
# 違う並びになり、かつ妥当性（その特性が高い型が上位に来やすい）は保たれる。
# =====================================================================
def make_rank_candidates(lang: str,
                         seed: str | None,
                         n: int,
                         recent_ids: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """自動アップ用: ランキングを n 枚ぶん（テーマ重複なし）生成して返す。

    recent_ids（直近のid）に含まれるテーマは避ける。各レコードは examples.jsonl
    互換なので、auto_uploader / card_video がそのまま使える。
    """
    from tools.rag_starter import gen_rank as gr

    sfx = "_en" if lang == "en" else ""
    pre = f"rank{sfx}_"
    recent_themes = {str(r)[len(pre):] for r in recent_ids if str(r).startswith(pre)}
    keys = [k for k in gr.all_theme_keys() if k not in recent_themes] or gr.all_theme_keys()

    rng = _seeded_rng(seed)
    rng.shuffle(keys)
    out: List[Dict[str, Any]] = []
    for key in keys[:max(0, n)]:
        _html_name, _script, rec = gr.make_random(lang, rng=rng, theme_key=key)
        out.append(rec)
    return out


# =====================================================================
# 組み合わせ（血液型×きょうだい／MBTI×きょうだい）も“核ランダム生成”で
# ---------------------------------------------------------------------
# 核 = (主軸コード, きょうだい順)。在庫から選ばず、毎回ランダムに核を選んで
# ルールでカードを生成する（同じ組み合わせのキャッシュを回避）。
# =====================================================================
def make_combo_candidates(genre: str,
                          lang: str,
                          seed: str | None,
                          n: int,
                          recent_ids: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """自動アップ用: 組み合わせカードを n 枚ぶん（核重複なし）生成して返す。

    genre は 'blood'（血液型×きょうだい）か 'mbti'（MBTI×きょうだい）。
    recent_ids に含まれる核（"<code>_<order>"）は避ける。
    """
    from tools.rag_starter import gen_combo as gco

    sfx = "_en" if lang == "en" else ""
    kind = gco.GENRES[genre]["kind"]
    pre = f"{kind}{sfx}_"
    recent_cores = {str(r)[len(pre):] for r in recent_ids if str(r).startswith(pre)}
    pool = [c for c in gco.cores(genre, lang)
            if f"{c[0]}_{c[1]}" not in recent_cores] or gco.cores(genre, lang)

    rng = _seeded_rng(seed)
    rng.shuffle(pool)
    out: List[Dict[str, Any]] = []
    for core in pool[:max(0, n)]:
        _html_name, rec = gco.make_random(genre, lang, rng=rng, core=core)
        out.append(rec)
    return out

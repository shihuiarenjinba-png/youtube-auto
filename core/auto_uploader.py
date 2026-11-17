# -*- coding: utf-8 -*-
"""
RAG 自動アップロード・エンジン（毎朝のカウント式自動投稿）
==========================================================
毎朝6時ごろ実行する想定の無人ジョブ本体。アプリで設定した1日の投稿上限（既定6本）の
うち「まだ使っていない残り枠ぶん」を、テンプレRAGコンテンツで自動アップする。

処理の流れ:
  1. 今日のAPI使用量（state）を見て残り枠を計算
  2. 今日の運勢ランキングを生成（最優先で1本確保）
  3. 残り枠を、テンプレ診断カード（干支/MBTI/星座/誕生数/色…）から日付シードで選んで埋める
  4. 各アイテム: HTML→PNG（Edge）→ ショート動画(mp4) → YouTubeへアップロード
  5. アップ済みID・本数を state に記録（二重投稿を防止）

★LLMは一切使いません。コンテンツもタイトル/概要欄も examples.jsonl のテンプレ
  情報（hook/caption/hashtags）から決定的に作るので、無人でも再現性が高く無料。

ログは logs/auto_upload_<date>.log に追記（アプリを閉じても後から追える）。
"""
from __future__ import annotations

import json
import hashlib
import importlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.zodiac_balance import balanced_daily_order, balanced_topic_order

ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "data" / "rag"
JSONL = RAG / "examples.jsonl"
HTML_DIR = RAG / "html"
IMG_DIR = RAG / "images"
CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"
STATE_PATH = CONFIG_DIR / "auto_upload_state.json"
ROUTES_PATH = CONFIG_DIR / "auto_upload_routes.json"
OUT_DIR = ROOT / "output" / "auto"
BGM_DIR = ROOT / "assets" / "bgm"
WINDOWS_EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

DAILY_API_LIMIT = 6          # App policy, not the YouTube API quota
DEDUP_WINDOW_DAYS = 14       # 直近この日数で上げたネタは避ける
SHORT_SECONDS = 8.0          # 1本の長さ（静止カードのKen Burns）
SECONDS_PER_CARD = 6.0       # セット動画で1枚あたりに見せる秒数
SET_SIZE = 3                 # 1本にまとめる同種・同言語カードの最大枚数

# 自動アップの“品質ゲート”。一定の基準をクリアしたものだけを母集団にし、
# その中から確率的（日付シード）に選ぶ。mbti_compat は相性スコアで足切り。
# 知覚軸（N同士/S同士）を共有する“ちゃんと相性が良い”ペアだけが対象になる。
# ※手動アップ（RAGタブ）は全120ペア使える。ゲートは自動だけに効く。
AUTO_MIN_SCORE = 85

# 運勢を最優先、その後この種類順でローテーション
KIND_PRIORITY = ["fortune", "eto", "mbti_compat", "rank", "blood_order", "mbti_order",
                 "mbti", "zodiac", "birthday", "color"]

# 運勢の後の“階層”。同じ階層内の種類は同列に扱い、残り枠を交互（ラウンドロビン）
# で案分する。人気枠（干支・MBTI相性・MBTIランキング・血液型きょうだい・MBTIきょうだい）
# を同列に。それ以外は単独階層のまま、上から順に消化。
# ※ plan_sets では下の GENRE_WEIGHTS による“重み付き抽選”を使う（KIND_TIERS は
#   旧 plan_today 用に残置）。
KIND_TIERS = [["eto", "mbti_compat", "rank", "blood_order", "mbti_order"],
              ["mbti"], ["zodiac"], ["birthday"], ["color"]]

# 自動アップのジャンル抽選の重み（運勢は先頭固定なので含めない）。
# 大きいほど“当たりやすい”＝露出が増える。被りは出さない（非復元抽選）。
GENRE_WEIGHTS = {
    "fortune_topic": 14, "zodiac": 12,
    "mbti_compat": 10, "rank": 10, "mbti_order": 8, "mbti": 6,
    "eto": 3, "blood_order": 3, "birthday": 2, "color": 1,
}
GENRE_WEIGHT_DEFAULT = 5

LANG_AUTO_KINDS = {
    "ja": set(),
    "en": set(),
}

# 6本/言語のときは fortune 1本 + TOP3 5本。各TOP3動画の先頭カードが
# タイトル化されやすいので、実績とShortsで見られやすい入口を先頭に置く。
FORTUNE_TOPIC_ORDER = [
    "love", "intuition", "wish",
    "encounter", "communication", "action",
    "money", "comeback", "decision",
    "work", "study", "health",
    "popularity", "healing", "night",
]

# English-only order. With SET_SIZE=3, the first item in each group becomes the
# video's lead theme and metadata theme. Keep this separate so Japanese output
# and its established rotation remain unchanged.
EN_FORTUNE_TOPIC_ORDER = [
    "love", "compatibility", "most_likely_love",
    "red_flags", "encounter", "communication",
    "toxic_traits", "intuition", "wish",
    "money", "most_likely_rich", "work",
    "most_likely_text_ex", "most_likely_viral", "most_likely_famous",
    "action", "comeback", "decision", "study", "health",
    "popularity", "healing", "night",
]

# Negative themes describe a temporary daily tendency, never a fixed character
# judgment. Multiple choices per sign keep consecutive videos from sounding
# mechanically identical.
EN_NEGATIVE_TRAIT_OPTIONS = {
    "aries": (
        "May act before thinking things through today.",
        "A little more impatient than usual today.",
        "Confidence may turn into rushing today.",
    ),
    "taurus": (
        "May dig in their heels a little too hard today.",
        "Extra stubborn today when plans suddenly change.",
        "Comfort may matter more than compromise today.",
    ),
    "gemini": (
        "May send mixed signals without meaning to today.",
        "A little more changeable than usual today.",
        "May talk around the point instead of choosing today.",
    ),
    "cancer": (
        "May take small comments a little too personally today.",
        "A little more sensitive than usual today.",
        "Mood may color the whole conversation today.",
    ),
    "leo": (
        "May crave a little too much attention today.",
        "A little more dramatic than usual today.",
        "Confidence may come on too strong today.",
    ),
    "virgo": (
        "May overthink every tiny detail today.",
        "A little more critical than usual today.",
        "Perfectionism may slow things down today.",
    ),
    "libra": (
        "May get a little carried away today.",
        "A little too confident about keeping everyone happy today.",
        "May avoid a clear choice longer than usual today.",
    ),
    "scorpio": (
        "May be a little more suspicious than usual today.",
        "Guarded feelings may be stronger today.",
        "May read too much into a small signal today.",
    ),
    "sagittarius": (
        "May avoid commitment a little more than usual today.",
        "Honesty may come out too bluntly today.",
        "Restlessness may make plans feel optional today.",
    ),
    "capricorn": (
        "May focus a little too much on work today.",
        "A little more controlling about the plan today.",
        "High standards may feel heavier than usual today.",
    ),
    "aquarius": (
        "May seem a little emotionally distant today.",
        "Independence may come before connection today.",
        "A little more detached than usual today.",
    ),
    "pisces": (
        "May get a little lost in their own world today.",
        "Boundaries may feel blurrier than usual today.",
        "May avoid a practical detail today.",
    ),
}

MONTHLY_RECAP_START = date(2026, 9, 1)
MONTHLY_RANK_POINTS = [15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


def _weighted_order(kinds, rnd) -> list:
    """ジャンルを“重み付き・非復元”で並べ替える。

    人気ジャンルほど前に来やすいが、一巡するまで同じジャンルは出ない（被らない）。
    これで「運要素（毎回順番が変わる）」と「きれいな並び（重複なし）」を両立する。
    """
    items = list(kinds)
    out = []
    while items:
        weights = [GENRE_WEIGHTS.get(k, GENRE_WEIGHT_DEFAULT) for k in items]
        pick = rnd.choices(items, weights=weights, k=1)[0]
        out.append(pick)
        items.remove(pick)
    return out


# =====================================================================
# ロギング
# =====================================================================
def _make_logger(day: date) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"auto_upload.{day.isoformat()}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_DIR / f"auto_upload_{day.isoformat()}.log",
                             encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# =====================================================================
# state（アップ済み台帳）
# =====================================================================
def _load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def _load_lang_channel_routes() -> Dict[str, str]:
    if ROUTES_PATH.exists():
        try:
            data = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                routes: Dict[str, str] = {}
                for k, v in data.items():
                    lang = str(k).strip().lower()
                    label = str(v).strip()
                    if lang in {"ja", "en"} and label:
                        routes[lang] = label
                return routes
        except Exception:
            pass
    return {}


def resolve_channel_for_lang(lang: str, fallback: Optional[str] = None) -> Optional[str]:
    """Resolve the upload channel for a language, using config/auto_upload_routes.json."""
    route = _load_lang_channel_routes().get((lang or "").strip().lower())
    return route or fallback


def _state_scope(lang: str = "", channel: Optional[str] = None) -> str:
    """Daily upload quotas are tracked per language/channel route."""
    lang_key = (lang or "").strip().lower() or "default"
    channel_key = (channel or "").strip() or "default"
    return f"{lang_key}:{channel_key}"


def _upload_lang(upload: Dict[str, Any]) -> str:
    if upload.get("lang"):
        return str(upload.get("lang", "")).strip().lower()
    ids = upload.get("ids") or [upload.get("id", "")]
    haystack = " ".join(str(x) for x in ids)
    if "_en_" in haystack or "fortune_en_" in haystack or "zodiac_en_" in haystack:
        return "en"
    return "ja"


def uploaded_today(state: Dict[str, Any], day: date,
                   lang: str = "", channel: Optional[str] = None) -> int:
    entry = state.get(day.isoformat(), {})
    if not lang and not channel:
        return int(entry.get("count", 0))
    scope = _state_scope(lang, channel)
    counts = entry.get("counts", {})
    if isinstance(counts, dict) and scope in counts:
        return int(counts.get(scope, 0))
    if lang:
        lang_key = (lang or "").strip().lower()
        return sum(1 for u in entry.get("uploads", []) if _upload_lang(u) == lang_key)
    return int(entry.get("count", 0))


def _recent_ids(state: Dict[str, Any], day: date) -> set:
    ids = set()
    for i in range(DEDUP_WINDOW_DAYS):
        d = (day - timedelta(days=i)).isoformat()
        ids.update(state.get(d, {}).get("ids", []))
    return ids


def _record_upload(state: Dict[str, Any], day: date, item_id: str,
                   video_url: str = "", lang: str = "",
                   channel: Optional[str] = None) -> None:
    key = day.isoformat()
    entry = state.setdefault(key, {"count": 0, "ids": [], "uploads": []})
    entry["count"] = int(entry.get("count", 0)) + 1
    scope = _state_scope(lang, channel)
    counts = entry.setdefault("counts", {})
    counts[scope] = int(counts.get(scope, 0)) + 1
    entry.setdefault("ids", []).append(item_id)
    entry.setdefault("uploads", []).append(
        {"id": item_id, "url": video_url, "lang": lang, "channel": channel or "",
         "at": datetime.now().isoformat(timespec="seconds")})
    _save_state(state)


# =====================================================================
# コンテンツ選定（LLM不使用・テンプレ＋日付シード）
# =====================================================================
def _load_records(lang: str) -> List[Dict[str, Any]]:
    rows = []
    if not JSONL.exists():
        return rows
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("lang", "ja") == lang and r.get("html"):
            rows.append(r)
    return rows


def _ensure_fortune(lang: str, day: date, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """今日の運勢（ランキング）を生成し、その先頭レコードを返す（旧 plan_today 用）。"""
    cards = _ensure_fortune_cards(lang, day, logger)
    return cards[0] if cards else None


def _ensure_fortune_cards(lang: str, day: date,
                          logger: logging.Logger) -> List[Dict[str, Any]]:
    """今日の運勢を生成し、ランキング＋スポットライトの2レコードを順に返す。

    gen_fortune(_en).py は1回の実行で2枚（ランキング/主役star）を焼き、JSONLに2件
    追記する。ここではそれを順番（ランキング→スポットライト）で拾って返す。
    生成に失敗しても、拾えたぶん（最低でもランキング）だけを返す＝運勢は止めない。
    """
    module_name = ("tools.rag_starter.gen_fortune_en" if lang == "en"
                   else "tools.rag_starter.gen_fortune")
    try:
        # The proven Windows version spawned .venv/Scripts/python.exe. GitHub-hosted
        # runners are Linux and ephemeral, so call the same build() implementation
        # in-process and persist only the records needed by the existing planner.
        module = importlib.import_module(module_name)
        generated = module.build(day)
        new_records = [record for _, record in generated]
        new_ids = {record["id"] for record in new_records}
        existing: List[str] = []
        if JSONL.exists():
            for raw in JSONL.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(raw).get("id") not in new_ids:
                        existing.append(raw)
                except Exception:
                    continue
        JSONL.parent.mkdir(parents=True, exist_ok=True)
        lines = existing + [json.dumps(record, ensure_ascii=False)
                            for record in new_records]
        JSONL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.warning(f"運勢の生成に失敗: {e}")
    base = f"fortune_en_{day.isoformat()}" if lang == "en" else f"fortune_{day.isoformat()}"
    by_id = {r.get("id"): r for r in _load_records(lang)}
    cards = [by_id[i] for i in (base, base + "_spot") if i in by_id]
    if cards:
        logger.info(f"運勢カード: {len(cards)}枚（ランキング＋主役star）を用意")
    return cards


def plan_today(lang: str, day: date, slots: int,
               state: Dict[str, Any], logger: logging.Logger) -> List[Dict[str, Any]]:
    """今日アップする順番付きアイテム一覧を作る（運勢→カードのローテーション）。

    干支(eto)とMBTI相性(mbti_compat)は“同列”として案分する。残り枠を両者で
    交互に取り合うラウンドロビンなので、4枠なら2:2、5枠なら3:2…と自動で案分。
    端数（例: 1.5枠）のリードは毎回ランダムに決まる＝長い目で見ればほぼ50:50。
    片方が尽きたら、もう片方が自然に引き継ぐ。
    それ以外の優劣（mbti > 星座 > 誕生数 > 色）は従来どおり保持する。
    """
    import random

    plan: List[Dict[str, Any]] = []
    if slots <= 0:
        return plan

    recent = _recent_ids(state, day)

    # 1) 運勢を最優先
    fortune = _ensure_fortune(lang, day, logger)
    if fortune and fortune["id"] not in recent:
        plan.append(fortune)

    # 2) 残り枠を、種類ごとのキューからランダムに選んで埋める
    rnd = random.Random()  # 毎回ランダム（運要素を持たせる／日付で固定しない）

    used = {p["id"] for p in plan}
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for r in _load_records(lang):
        k = r.get("kind")
        if k == "fortune" or r["id"] in recent or r["id"] in used:
            continue
        by_kind.setdefault(k, []).append(r)
    for k in by_kind:
        rnd.shuffle(by_kind[k])  # 毎回ランダムにシャッフル

    # 階層（tier）順に消化。最初の階層内は“同列＝案分”のラウンドロビン。
    for tier in KIND_TIERS:
        order = [k for k in tier if by_kind.get(k)]
        rnd.shuffle(order)  # 端数のリードを当日シードで決定（ほぼ50:50）
        while len(plan) < slots and any(by_kind.get(k) for k in order):
            for k in order:
                if len(plan) >= slots:
                    break
                if by_kind.get(k):
                    plan.append(by_kind[k].pop(0))
        if len(plan) >= slots:
            break

    return plan[:slots]


def _auto_eligible(r: Dict[str, Any]) -> bool:
    """自動アップの品質ゲート。基準を満たすものだけ True。"""
    if r.get("kind") == "mbti_compat":
        # 相性スコアが基準未満（知覚軸が違う＝相性が伸びにくいペア）は自動では使わない
        return int(r.get("score", 0)) >= AUTO_MIN_SCORE
    return True


def _make_compat_candidates(lang: str, day: date, recent: set, n: int,
                            logger: logging.Logger) -> List[Dict[str, Any]]:
    """MBTI相性: “核(型ペア)”をランダムに選び、その場でルール生成したカード群を返す。

    在庫(jsonl)から選ぶのではなく、核を毎回ランダムに決めて生成する（運要素）。
    品質ゲート(AUTO_MIN_SCORE)で足切りし、直近で使った核は避ける。
    """
    from core.rag_factory import make_compat_candidates
    cards = make_compat_candidates(lang, seed=None, n=n,
                                   min_score=AUTO_MIN_SCORE, recent_ids=recent)
    if cards:
        logger.info(f"相性カード: 核をランダム選択して{len(cards)}枚を生成（在庫からの選択ではない）")
    return cards


def _make_rank_candidates(lang: str, day: date, recent: set, n: int,
                          logger: logging.Logger) -> List[Dict[str, Any]]:
    """MBTIランキング: テーマ・並び順をその場でランダムに決めて生成したカード群を返す。

    在庫(jsonl)から選ぶと“同じ並び”がキャッシュされるため、毎回ランダムに作る。
    重みつきテーマでも乱数ゆらぎで並びが変わり、妥当性（上位の納得感）は保たれる。
    """
    from core.rag_factory import make_rank_candidates
    cards = make_rank_candidates(lang, seed=None, n=n, recent_ids=recent)
    if cards:
        logger.info(f"ランキング: テーマと並びをランダムに決めて{len(cards)}枚を生成（在庫からの選択ではない）")
    return cards


def _make_combo_candidates(genre: str, lang: str, day: date, recent: set, n: int,
                           logger: logging.Logger) -> List[Dict[str, Any]]:
    """血液型×きょうだい / MBTI×きょうだい: 核(主軸×きょうだい順)をランダム生成。"""
    from core.rag_factory import make_combo_candidates
    cards = make_combo_candidates(genre, lang, seed=None, n=n, recent_ids=recent)
    if cards:
        label = "血液型きょうだい" if genre == "blood" else "MBTIきょうだい"
        logger.info(f"{label}: 核をランダムに選んで{len(cards)}枚を生成（在庫からの選択ではない）")
    return cards


def _kind_allowed(lang: str, kind: Optional[str]) -> bool:
    allowed = LANG_AUTO_KINDS.get((lang or "").strip().lower())
    return True if allowed is None else kind in allowed


def _topic_config(lang: str) -> Dict[str, Dict[str, Any]]:
    if lang == "en":
        return {
            "love": {
                "title": "Love Luck TOP3",
                "youtube_title": "Zodiac Signs Ranked by Love Luck Today | {date}",
                "theme_hashtag": "#LoveHoroscope",
                "cta": "Agree or disagree?",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should take one gentle step today",
                "hashtags": ["#horoscope", "#zodiac", "#loveluck", "#shorts"],
                "comments": [
                    "Send the kind message. It may land better than expected.",
                    "Show a little warmth first and the mood can soften.",
                    "One honest moment could move things forward today.",
                ],
                "foot": "Not in the TOP3? Keep it gentle; one calm reply still helps.",
            },
            "money": {
                "title": "Money Luck TOP3",
                "youtube_title": "Zodiac Signs Ranked by Money Luck Today | {date}",
                "theme_hashtag": "#MoneyHoroscope",
                "cta": "Which sign would you rank #1?",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should make one smart money move",
                "hashtags": ["#horoscope", "#zodiac", "#moneyluck", "#shorts"],
                "comments": [
                    "Review one payment or plan. A small fix can pay off.",
                    "Your eye for value is clear, so choose with intention.",
                    "Wait before buying; better timing may appear today.",
                ],
                "foot": "Not in the TOP3? Pause one impulse buy and you still win.",
            },
            "compatibility": {
                "title": "Zodiac Compatibility TOP3",
                "youtube_title": "Zodiac Compatibility Ranked Today | {date}",
                "theme_hashtag": "#ZodiacCompatibility",
                "cta": "Which sign would you rank #1?",
                "kicker": "TODAY'S CONNECTIONS",
                "subtitle": "Signs most ready to connect and understand each other",
                "hashtags": ["#zodiac", "#compatibility", "#shorts"],
                "comments": [
                    "Open communication can make a promising bond feel easier today.",
                    "Shared energy may help this sign meet others halfway today.",
                    "A thoughtful reply could strengthen an important connection today.",
                ],
                "foot": "Good connections still grow through honesty and mutual effort.",
            },
            "most_likely_love": {
                "title": "Most Likely to Fall in Love First",
                "youtube_title": "Most Likely to Fall in Love First | {date}",
                "theme_hashtag": "#LoveHoroscope",
                "cta": "Which sign would you rank #1?",
                "kicker": "MOST LIKELY TO",
                "subtitle": "Signs whose hearts may move first today",
                "hashtags": ["#zodiac", "#lovehoroscope", "#shorts"],
                "comments": [
                    "A small spark may feel surprisingly meaningful today.",
                    "Warm attention could turn into real curiosity today.",
                    "One honest moment may open the heart today.",
                ],
                "foot": "A genuine connection can begin with one simple conversation.",
            },
            "most_likely_text_ex": {
                "title": "Most Likely to Text Their Ex",
                "youtube_title": "Most Likely to Text Their Ex | {date}",
                "theme_hashtag": "#LoveHoroscope",
                "cta": "Agree or disagree?",
                "kicker": "MOST LIKELY TO",
                "subtitle": "Signs feeling a little nostalgic today",
                "hashtags": ["#zodiac", "#lovehoroscope", "#shorts"],
                "comments": [
                    "A familiar memory may be harder to ignore today.",
                    "Nostalgia could make an old chat feel tempting today.",
                    "A past connection may cross their mind again today.",
                ],
                "foot": "Pause before sending and choose what supports you now.",
            },
            "most_likely_rich": {
                "title": "Most Likely to Become Rich",
                "youtube_title": "Most Likely to Become Rich | {date}",
                "theme_hashtag": "#MoneyHoroscope",
                "cta": "Which sign would you rank #1?",
                "kicker": "MOST LIKELY TO",
                "subtitle": "Signs spotting the smartest opportunity today",
                "hashtags": ["#zodiac", "#moneyhoroscope", "#shorts"],
                "comments": [
                    "A practical idea may have long-term value today.",
                    "Patient choices could create useful momentum today.",
                    "One smart adjustment may improve the money picture today.",
                ],
                "foot": "Strong money habits matter more than one lucky moment.",
            },
            "most_likely_viral": {
                "title": "Most Likely to Go Viral",
                "youtube_title": "Most Likely to Go Viral | {date}",
                "theme_hashtag": "#MostLikelyTo",
                "cta": "Which sign would you rank #1?",
                "kicker": "MOST LIKELY TO",
                "subtitle": "Signs whose ideas may travel farther today",
                "hashtags": ["#zodiac", "#mostlikelyto", "#shorts"],
                "comments": [
                    "A timely idea may connect with more people today.",
                    "Their natural voice could stand out online today.",
                    "One bold post may find the right audience today.",
                ],
                "foot": "Keep it genuine; the clearest idea often travels farthest.",
            },
            "most_likely_famous": {
                "title": "Most Likely to Become Famous",
                "youtube_title": "Most Likely to Become Famous | {date}",
                "theme_hashtag": "#MostLikelyTo",
                "cta": "Which sign would you rank #1?",
                "kicker": "MOST LIKELY TO",
                "subtitle": "Signs whose presence may stand out today",
                "hashtags": ["#zodiac", "#mostlikelyto", "#shorts"],
                "comments": [
                    "Their presence may be especially memorable today.",
                    "A confident moment could draw the right attention today.",
                    "A unique strength may be easier for others to notice today.",
                ],
                "foot": "Recognition grows when real strengths stay visible.",
            },
            "red_flags": {
                "title": "Red Flag Energy TOP3",
                "youtube_title": "Zodiac Signs Most Likely to Be a Red Flag Today | {date}",
                "theme_hashtag": "#RedFlags",
                "negative": True,
                "cta": "Agree or disagree?",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Temporary habits worth watching today",
                "hashtags": ["#zodiac", "#redflags", "#shorts"],
                "comments": ["A temporary habit may need a little extra awareness today."],
                "sign_comments": EN_NEGATIVE_TRAIT_OPTIONS,
                "foot": "Every sign has its good side ✨",
            },
            "toxic_traits": {
                "title": "Toxic Traits Today TOP3",
                "youtube_title": "Zodiac Signs Ranked by Today's Toxic Traits | {date}",
                "theme_hashtag": "#ToxicTraits",
                "negative": True,
                "cta": "Agree or disagree?",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Tricky tendencies to keep in check today",
                "hashtags": ["#zodiac", "#toxictraits", "#shorts"],
                "comments": ["A temporary tendency may need a little extra balance today."],
                "sign_comments": EN_NEGATIVE_TRAIT_OPTIONS,
                "foot": "Every sign has its good side ✨",
            },
            "work": {
                "title": "Work Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should start with one clear task",
                "hashtags": ["#horoscope", "#zodiac", "#workluck", "#shorts"],
                "comments": [
                    "Pick the one task you keep avoiding and begin there.",
                    "A steady effort could be noticed in the right place.",
                    "Choose one clear task and your focus can return.",
                ],
                "foot": "Not in the TOP3? Clean up one task and the day can shift.",
            },
            "encounter": {
                "title": "Encounter Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should open one small door",
                "hashtags": ["#horoscope", "#zodiac", "#newconnections", "#shorts"],
                "comments": [
                    "Say yes to a light conversation; it could lead somewhere.",
                    "Reach out first if someone crosses your mind today.",
                    "A casual hello may bring a surprisingly good link.",
                ],
                "foot": "Not in the TOP3? Be approachable; one greeting is enough.",
            },
            "communication": {
                "title": "Communication TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should speak a little softer",
                "hashtags": ["#horoscope", "#zodiac", "#communication", "#shorts"],
                "comments": [
                    "Choose simple words and the right person may understand.",
                    "Listening first can turn the whole conversation around.",
                    "A small follow-up could repair more than you expect.",
                ],
                "foot": "Not in the TOP3? Reply slowly and your luck stays steady.",
            },
            "action": {
                "title": "Action Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should move before overthinking",
                "hashtags": ["#horoscope", "#zodiac", "#takeaction", "#shorts"],
                "comments": [
                    "Start before it feels perfect. Momentum may meet you there.",
                    "A ten-minute action could open a bigger path today.",
                    "Do the first small step and let confidence catch up.",
                ],
                "foot": "Not in the TOP3? Set a timer for five minutes and begin.",
            },
            "intuition": {
                "title": "Intuition TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should trust the first quiet signal",
                "hashtags": ["#horoscope", "#zodiac", "#intuition", "#shorts"],
                "comments": [
                    "Write down the idea before you talk yourself out of it.",
                    "Your first impression may be more useful than it seems.",
                    "Follow the calm yes, not the noisy pressure.",
                ],
                "foot": "Not in the TOP3? Keep notes today; one clue may matter.",
            },
            "comeback": {
                "title": "Comeback Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that can turn the day around",
                "hashtags": ["#horoscope", "#zodiac", "#comeback", "#shorts"],
                "comments": [
                    "Restart the thing you almost gave up on.",
                    "A second attempt may work better than the first today.",
                    "Reset your pace; the afternoon can still surprise you.",
                ],
                "foot": "Not in the TOP3? One reset is enough to change the mood.",
            },
            "wish": {
                "title": "Wish Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should name what they want",
                "hashtags": ["#horoscope", "#zodiac", "#manifestation", "#shorts"],
                "comments": [
                    "Say the wish plainly. Clear words can attract support.",
                    "Ask for one small thing instead of carrying it alone.",
                    "Put the wish on paper and make it a little more real.",
                ],
                "foot": "Not in the TOP3? Write one wish down and keep moving.",
            },
            "healing": {
                "title": "Healing Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should choose rest without guilt",
                "hashtags": ["#horoscope", "#zodiac", "#selfcare", "#shorts"],
                "comments": [
                    "Take the quiet break. Your energy may come back faster.",
                    "Do one kind thing for your body and let that count.",
                    "Lower the pressure and the day can feel lighter.",
                ],
                "foot": "Not in the TOP3? Three slow breaths can still reset you.",
            },
            "night": {
                "title": "Night Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs whose luck may rise later today",
                "hashtags": ["#horoscope", "#zodiac", "#nightluck", "#shorts"],
                "comments": [
                    "Do not judge the day too early; the later hours may help.",
                    "Save one meaningful task for the evening if you can.",
                    "A delayed answer could arrive at just the right time.",
                ],
                "foot": "Not in the TOP3? Keep the evening simple and restorative.",
            },
            "decision": {
                "title": "Decision Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should simplify one choice",
                "hashtags": ["#horoscope", "#zodiac", "#decision", "#shorts"],
                "comments": [
                    "Narrow the options and the right choice may stand out.",
                    "Do not ignore the small feeling that says wait.",
                    "Choose the steady path, then take one practical step.",
                ],
                "foot": "Not in the TOP3? Remove one option and breathe easier.",
            },
            "popularity": {
                "title": "Popularity Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs whose natural charm can travel farther",
                "hashtags": ["#horoscope", "#zodiac", "#charm", "#shorts"],
                "comments": [
                    "Be visible in a simple way; your presence may land well.",
                    "A relaxed smile can do more than a perfect performance.",
                    "Let your real tone show. It may be exactly what works.",
                ],
                "foot": "Not in the TOP3? Tidy one detail and your impression lifts.",
            },
            "study": {
                "title": "Study Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should learn in short focused bursts",
                "hashtags": ["#horoscope", "#zodiac", "#studyluck", "#shorts"],
                "comments": [
                    "Review first; the new piece may click faster today.",
                    "Ten focused minutes can beat one distracted hour.",
                    "Start with the hard part while your mind is fresh.",
                ],
                "foot": "Not in the TOP3? Review one note and count it as progress.",
            },
            "health": {
                "title": "Wellness Luck TOP3",
                "kicker": "TODAY'S ZODIAC",
                "subtitle": "Signs that should support the body first",
                "hashtags": ["#horoscope", "#zodiac", "#wellness", "#shorts"],
                "comments": [
                    "Move gently and your mood may follow.",
                    "Warm food, water, and sleep can shift your whole day.",
                    "One healthy choice could make everything feel clearer.",
                ],
                "foot": "Not in the TOP3? Stretch your neck and shoulders today.",
            },
        }
    return {
        "love": {
            "title": "恋愛運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "心の距離が近づきやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#恋愛運", "#shorts"],
            "comments": [
                "素直な一言が、思った以上に届きやすい日。",
                "やさしい空気をまとえて、自然に距離が縮まります。",
                "小さな気遣いが、好印象として残りそう。",
            ],
            "foot": "TOP3以外でも、今日は焦らず聞き役に回ると運気回復。",
        },
        "money": {
            "title": "金運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "お金の流れを整えやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#金運", "#shorts"],
            "comments": [
                "必要なものを見極める目が冴えています。",
                "小さな節約や見直しが、あとで効いてきそう。",
                "買うより整える意識で、運の流れが上向きます。",
            ],
            "foot": "TOP3以外でも、衝動買いを一度止めれば十分巻き返せます。",
        },
        "work": {
            "title": "仕事運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "集中力と段取りが味方する星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#仕事運", "#shorts"],
            "comments": [
                "やるべきことが自然に整理され、前へ進めます。",
                "丁寧な対応が信頼につながりやすい日。",
                "ひとつに絞るほど、成果が見えやすくなります。",
            ],
            "foot": "TOP3以外でも、最初の5分だけ整えると流れが戻ります。",
        },
        "encounter": {
            "title": "出会い運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "人との縁が動きやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#出会い運", "#shorts"],
            "comments": [
                "何気ない会話から、いい流れが始まりそう。",
                "久しぶりの連絡や偶然の再会にツキがあります。",
                "自分から少し近づくと、縁がほどけていきます。",
            ],
            "foot": "TOP3以外でも、あいさつを少し丁寧にすると運が動きます。",
        },
        "communication": {
            "title": "対人運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "人間関係がなめらかに進む星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#対人運", "#shorts"],
            "comments": [
                "言葉選びがやわらかく、誤解をほどきやすい日。",
                "相手の本音を受け止める余裕が出てきます。",
                "小さなフォローが、信頼として戻ってきそう。",
            ],
            "foot": "TOP3以外でも、今日は返事を急がないだけで安定します。",
        },
        "action": {
            "title": "行動運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "一歩踏み出すほど流れが来る星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#開運行動", "#shorts"],
            "comments": [
                "先延ばしにしていたことほど、動かす価値あり。",
                "短時間の行動が、思った以上の突破口になります。",
                "完璧より先に着手すると、運が味方します。",
            ],
            "foot": "TOP3以外でも、机の上を整えるだけで流れが変わります。",
        },
        "intuition": {
            "title": "直感運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "ひらめきがチャンスにつながる星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#直感", "#shorts"],
            "comments": [
                "ふと思いついた案を、メモしておくと後で効きます。",
                "違和感とワクワク、どちらも大事なサインです。",
                "考えすぎる前の第一印象にヒントがあります。",
            ],
            "foot": "TOP3以外でも、今日はメモを残すほど運を拾えます。",
        },
        "comeback": {
            "title": "逆転運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "午後から巻き返しやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#逆転運", "#shorts"],
            "comments": [
                "朝の遅れを、午後の集中力で取り戻せそう。",
                "一度止まった話に、もう一度光が差します。",
                "諦めずに整え直すほど、結果が変わります。",
            ],
            "foot": "TOP3以外でも、今日は夕方の一手を大事に。",
        },
        "wish": {
            "title": "願いごと運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "小さな願いが形になりやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#願いごと", "#shorts"],
            "comments": [
                "言葉にした願いほど、現実へ近づきやすい日。",
                "小さな希望を遠慮せず出すと流れが変わります。",
                "誰かの助けで、思ったより早く前進しそう。",
            ],
            "foot": "TOP3以外でも、願いをひとつ書くと気持ちが整います。",
        },
        "healing": {
            "title": "癒やし運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "心と体を整えるほど運が上がる星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#癒やし", "#shorts"],
            "comments": [
                "無理を減らすほど、本来の調子が戻ってきます。",
                "静かな時間が、次の元気を連れてきます。",
                "自分を責めない選択が、今日の開運になります。",
            ],
            "foot": "TOP3以外でも、深呼吸を3回。そこから運が戻ります。",
        },
        "night": {
            "title": "夜に伸びる運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "一日の後半に流れが良くなる星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#夜の運勢", "#shorts"],
            "comments": [
                "夜に近づくほど、気持ちと流れが噛み合います。",
                "今日の答えは、少し遅れてやってきそう。",
                "焦らず待つことで、ちょうどいい展開に。",
            ],
            "foot": "TOP3以外でも、夜はスマホ時間を短めにすると回復します。",
        },
        "decision": {
            "title": "決断運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "迷いを整理して選びやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#決断運", "#shorts"],
            "comments": [
                "答えを急がず比べるほど、自然に選べます。",
                "小さな違和感を無視しないことが開運に。",
                "今日は直感と現実感のバランスが取れています。",
            ],
            "foot": "TOP3以外でも、選択肢を2つに絞ると動きやすくなります。",
        },
        "popularity": {
            "title": "人気運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "自然な魅力が伝わりやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#人気運", "#shorts"],
            "comments": [
                "飾らない一言が、周りの心に残ります。",
                "無理に目立たなくても、存在感が伝わる日。",
                "笑顔と余裕が、思った以上の味方を呼びます。",
            ],
            "foot": "TOP3以外でも、今日は清潔感を整えるだけで印象アップ。",
        },
        "study": {
            "title": "勉強運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "吸収力と理解力が上がりやすい星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#勉強運", "#shorts"],
            "comments": [
                "短い集中を重ねるほど、頭に入りやすい日。",
                "苦手な部分ほど、今日は突破口が見つかります。",
                "復習から入ると、新しい理解につながります。",
            ],
            "foot": "TOP3以外でも、10分だけ復習すると運が整います。",
        },
        "health": {
            "title": "健康運TOP3",
            "kicker": "今日の星座占い",
            "subtitle": "体調を整えるほど前向きになれる星座",
            "hashtags": ["#今日の運勢", "#星座占い", "#健康運", "#shorts"],
            "comments": [
                "軽く体を動かすと、気分まで切り替わります。",
                "温かい飲み物や休憩が、運の底上げに。",
                "睡眠と食事を整えるほど、集中力が戻ります。",
            ],
            "foot": "TOP3以外でも、今日は首と肩をゆるめると楽になります。",
        },
    }


def _is_month_end(day: date) -> bool:
    return day.day == calendar.monthrange(day.year, day.month)[1]


def _monthly_recap_enabled(day: date) -> bool:
    return day >= MONTHLY_RECAP_START and _is_month_end(day)


def _month_days(day: date) -> List[date]:
    last = calendar.monthrange(day.year, day.month)[1]
    return [date(day.year, day.month, d) for d in range(1, last + 1)]


def _month_label(lang: str, day: date) -> str:
    if lang == "en":
        return day.strftime("%B %Y")
    return f"{day.year}年{day.month}月"


def _monthly_recap_stats(signs: List[Dict[str, Any]], day: date) -> List[Dict[str, Any]]:
    by_code = {str(s.get("code", "")): s for s in signs if s.get("code")}
    rows = {code: {"sign": sign, "points": 0, "top1": 0, "top3": 0}
            for code, sign in by_code.items()}
    for d in _month_days(day):
        order = balanced_daily_order(signs, d)
        for rank, sign in enumerate(order, start=1):
            code = str(sign.get("code", ""))
            if code not in rows:
                continue
            rows[code]["points"] += MONTHLY_RANK_POINTS[rank - 1]
            if rank == 1:
                rows[code]["top1"] += 1
            if rank <= 3:
                rows[code]["top3"] += 1
    return sorted(rows.values(),
                  key=lambda r: (-int(r["points"]), -int(r["top1"]), -int(r["top3"]),
                                 str(r["sign"].get("name", ""))))


def _monthly_recap_html(lang: str, day: date, stats: List[Dict[str, Any]]) -> str:
    import html
    is_en = lang == "en"
    label = _month_label(lang, day)
    title = "Monthly Zodiac Points TOP3" if is_en else "今月ポイント王TOP3"
    subtitle = "Monthly battle scored from the daily zodiac rankings" if is_en else "毎日の12星座ランキングをポイント対決"
    top_label = "Wins" if is_en else "1位"
    top3_label = "TOP3"
    times = "times" if is_en else "回"
    points = "pt" if is_en else "pt"
    foot = ("A monthly look back from the daily zodiac rankings. Watch for next month too."
            if is_en else "1位15pt、2位12pt、3位10ptから最下位1ptで集計。来月も期待です。")
    font = "'Segoe UI', Arial, sans-serif" if is_en else "'Meiryo', 'Yu Gothic', sans-serif"
    rows = []
    for idx, row in enumerate(stats, start=1):
        sign = row["sign"]
        cls = "row top" if idx <= 3 else "row"
        rank_text = f"TOP {idx}" if is_en and idx <= 3 else f"TOP{idx}" if idx <= 3 else str(idx)
        rows.append(
            f'<div class="{cls}">'
            f'<div class="rank">{rank_text}</div>'
            f'<div class="name">{html.escape(str(sign.get("name", "")))}</div>'
            f'<div class="count">{int(row["points"])}{points}</div>'
            f'<div class="subcount">{top_label} {int(row["top1"])}{times} / {top3_label} {int(row["top3"])}{times}</div>'
            f'</div>'
        )
    return f"""<!DOCTYPE html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: 1080px; height: 1920px; }}
  body {{
    font-family: {font};
    background: linear-gradient(155deg, #202329 0%, #2f5d62 48%, #d99a3d 100%);
    color: #fff; display: flex; flex-direction: column; align-items: center;
    padding: 78px 58px 58px;
  }}
  .kicker {{ font-size: 32px; font-weight: 900; letter-spacing: 4px; opacity: .88; }}
  .title {{ font-size: 82px; font-weight: 900; margin-top: 20px; line-height: 1.04;
    text-align: center; text-shadow: 0 5px 24px rgba(0,0,0,.32); }}
  .date {{ font-size: 36px; font-weight: 900; margin-top: 18px; padding: 9px 30px;
    background: rgba(255,255,255,.15); border-radius: 999px; }}
  .sub {{ font-size: 34px; font-weight: 800; line-height: 1.28; text-align: center;
    margin-top: 30px; opacity: .96; }}
  .list {{ width: 100%; margin-top: 48px; display: grid; grid-template-columns: 1fr 1fr;
    gap: 16px; }}
  .row {{ min-height: 124px; border-radius: 22px; padding: 18px 20px;
    background: rgba(255,255,255,.14); border: 2px solid rgba(255,255,255,.18);
    display: grid; grid-template-columns: 58px 1fr; column-gap: 14px; align-items: center; }}
  .row.top {{ background: rgba(255,244,184,.94); color: #34290d; }}
  .rank {{ grid-row: span 2; font-size: 34px; font-weight: 900; text-align: center; }}
  .name {{ font-size: 38px; font-weight: 900; line-height: 1.05; }}
  .count {{ font-size: 31px; font-weight: 900; margin-top: 6px; }}
  .subcount {{ font-size: 24px; font-weight: 800; opacity: .82; }}
  .foot {{ margin-top: auto; font-size: 30px; line-height: 1.35; text-align: center;
    opacity: .94; padding-top: 30px; }}
</style>
</head>
<body>
  <div class="kicker">{html.escape(label)}</div>
  <div class="title">{html.escape(title)}</div>
  <div class="date">{html.escape(subtitle)}</div>
  <div class="sub">{html.escape(str(stats[0]["sign"].get("name", "")))} {int(stats[0]["points"])}{points}</div>
  <div class="list">{''.join(rows)}</div>
  <div class="foot">{html.escape(foot)}</div>
</body>
</html>
"""


def _make_monthly_recap(lang: str, day: date, recent: set,
                        logger: logging.Logger) -> Optional[Dict[str, Any]]:
    if not _monthly_recap_enabled(day):
        return None
    data_file = "zodiac_en.json" if lang == "en" else "zodiac.json"
    try:
        signs = json.loads((RAG / "knowledge" / data_file).read_text(encoding="utf-8"))["signs"]
    except Exception as e:
        logger.warning(f"月末ランキングカードの生成に失敗（知識ファイル）: {e}")
        return None
    prefix = "monthly_recap_en" if lang == "en" else "monthly_recap"
    item_id = f"{prefix}_{day.year}-{day.month:02d}"
    if item_id in recent:
        return None
    stats = _monthly_recap_stats(signs, day)
    if not stats:
        return None
    html_name = f"{item_id}.html"
    (HTML_DIR / html_name).write_text(
        _monthly_recap_html(lang, day, stats),
        encoding="utf-8",
    )
    top = stats[0]["sign"]
    top_name = str(top.get("name", ""))
    top_points = int(stats[0]["points"])
    if lang == "en":
        hook = f"{_month_label(lang, day)} zodiac points TOP3! {top_name} leads"
        caption = f"{top_name} led this month's zodiac points battle with {top_points}pt. Watch for next month too."
        hashtags = ["#horoscope", "#zodiac", "#monthlyranking", "#shorts"]
        genre = "Monthly Zodiac Recap"
    else:
        hook = f"{day.month}月の星座ポイントTOP3！トップは{top_name}"
        caption = f"{day.month}月の12星座ランキングを集計。ポイント王は{top_name}、{top_points}pt。来月も期待。"
        hashtags = ["#今月の運勢", "#星座占い", "#ランキング", "#shorts"]
        genre = "今月の星座ランキング"
    logger.info(f"月末ランキングカード: {item_id} を用意")
    return {
        "id": item_id,
        "genre": genre,
        "format": "monthly zodiac recap HTML",
        "kind": "monthly_recap",
        "lang": lang,
        "html": f"html/{html_name}",
        "hook": hook,
        "caption": caption,
        "hashtags": hashtags,
    }


def _zodiac_top3_html(lang: str, day: date, cfg: Dict[str, Any],
                      top3: List[Dict[str, Any]]) -> str:
    import html
    is_en = lang == "en"
    date_str = (f"{day.strftime('%b')} {day.day}, {day.year}"
                if is_en else f"{day.month}月{day.day}日")
    rank_word = "No." if is_en else ""
    rank_suffix = "" if is_en else "位"
    rows = []
    for idx, sign in enumerate(top3, start=1):
        choices = (cfg.get("sign_comments", {}).get(str(sign.get("code", "")).lower())
                   or cfg["comments"])
        if cfg.get("sign_comments"):
            seed_text = (f"{day.isoformat()}:{cfg.get('title', '')}:"
                         f"{sign.get('code', '')}:{idx}")
            choice_index = int.from_bytes(
                hashlib.sha256(seed_text.encode("utf-8")).digest()[:4], "big"
            ) % len(choices)
        else:
            choice_index = (idx - 1) % len(choices)
        comment = choices[choice_index]
        rows.append(
            f'<div class="pick p{idx}">'
            f'<div class="rank">{rank_word}{idx}{rank_suffix}</div>'
            f'<div class="name">{html.escape(str(sign.get("name", "")))}</div>'
            f'<div class="copy">{html.escape(comment)}</div>'
            f'</div>'
        )
    font = "'Segoe UI', Arial, sans-serif" if is_en else "'Meiryo', 'Yu Gothic', sans-serif"
    return f"""<!DOCTYPE html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: 1080px; height: 1920px; }}
  body {{
    font-family: {font};
    background: linear-gradient(155deg, #181821 0%, #354f52 48%, #c77d3a 100%);
    color: #fff; display: flex; flex-direction: column; align-items: center;
    padding: 76px 60px 58px;
  }}
  .kicker {{ font-size: 32px; font-weight: 900; letter-spacing: 4px; opacity: .9; }}
  .title {{ font-size: 86px; font-weight: 900; margin-top: 20px; line-height: 1.02;
    text-align: center; text-shadow: 0 5px 24px rgba(0,0,0,.32); }}
  .date {{ font-size: 34px; font-weight: 900; margin-top: 18px; padding: 9px 30px;
    background: rgba(255,255,255,.14); border-radius: 999px; }}
  .sub {{ font-size: 34px; font-weight: 800; line-height: 1.28; text-align: center;
    margin-top: 34px; opacity: .96; }}
  .list {{ width: 100%; margin-top: 58px; display: flex; flex-direction: column; gap: 26px; }}
  .pick {{ min-height: 250px; border-radius: 24px; padding: 30px 34px;
    background: rgba(255,255,255,.13); border: 2px solid rgba(255,255,255,.18);
    display: grid; grid-template-columns: 160px 1fr; column-gap: 24px; align-items: center; }}
  .pick.p1 {{ background: rgba(255,244,184,.97); color: #32270a; }}
  .pick.p2 {{ background: rgba(255,255,255,.92); color: #23343a; }}
  .pick.p3 {{ background: rgba(250,206,160,.94); color: #3b2213; }}
  .rank {{ font-size: 48px; font-weight: 900; text-align: center; }}
  .name {{ font-size: 62px; font-weight: 900; line-height: 1.02; }}
  .copy {{ grid-column: 2; font-size: 32px; line-height: 1.34; margin-top: 14px; }}
  .foot {{ margin-top: auto; font-size: 30px; line-height: 1.35; text-align: center;
    opacity: .94; padding-top: 34px; }}
</style>
</head>
<body>
  <div class="kicker">{html.escape(cfg["kicker"])}</div>
  <div class="title">{html.escape(cfg["title"])}</div>
  <div class="date">{html.escape(date_str)}</div>
  <div class="sub">{html.escape(cfg["subtitle"])}</div>
  <div class="list">{''.join(rows)}</div>
  <div class="foot">{html.escape(cfg["foot"])}</div>
</body>
</html>
"""


def _make_fortune_topic_candidates(lang: str, day: date, recent: set,
                                   logger: logging.Logger,
                                   limit: Optional[int] = None) -> List[Dict[str, Any]]:
    data_file = "zodiac_en.json" if lang == "en" else "zodiac.json"
    try:
        signs = json.loads((RAG / "knowledge" / data_file).read_text(encoding="utf-8"))["signs"]
    except Exception as e:
        logger.warning(f"星座TOP3カードの生成に失敗（知識ファイル）: {e}")
        return []

    out: List[Dict[str, Any]] = []
    topic_config = _topic_config(lang)
    preferred_order = EN_FORTUNE_TOPIC_ORDER if lang == "en" else FORTUNE_TOPIC_ORDER
    ordered_topics = [t for t in preferred_order if t in topic_config]
    ordered_topics.extend(t for t in topic_config if t not in ordered_topics)
    for topic in ordered_topics:
        cfg = topic_config[topic]
        if limit is not None and len(out) >= limit:
            break
        prefix = "fortune_topic_en" if lang == "en" else "fortune_topic"
        item_id = f"{prefix}_{topic}_{day.isoformat()}"
        if item_id in recent:
            continue
        ordered = balanced_topic_order(signs, day, topic, ordered_topics)
        top3 = ordered[:3]
        html_name = f"{item_id}.html"
        (HTML_DIR / html_name).write_text(
            _zodiac_top3_html(lang, day, cfg, top3),
            encoding="utf-8",
        )
        names = [str(s.get("name", "")) for s in top3]
        if lang == "en":
            hook = f"{cfg['title']} today: No.1 is {names[0]}"
            caption = f"Today's {cfg['title'].lower()} zodiac ranking: {', '.join(names)}."
        else:
            hook = f"今日の{cfg['title']}！1位は{names[0]}"
            caption = f"今日の{cfg['title']}は、{names[0]}・{names[1]}・{names[2]}に注目。"
        out.append({
            "id": item_id,
            "topic": topic,
            "genre": cfg["title"],
            "format": "zodiac top3 HTML",
            "kind": "fortune_topic",
            "lang": lang,
            "html": f"html/{html_name}",
            "hook": hook,
            "caption": caption,
            "hashtags": cfg["hashtags"],
        })
    if out:
        logger.info(f"星座TOP3カード: {len(out)}枚を用意")
    return out


def plan_sets(lang: str, day: date, slots: int,
              state: Dict[str, Any], logger: logging.Logger,
              set_size: int = SET_SIZE) -> List[List[Dict[str, Any]]]:
    """今日の“セット”一覧を作る。各セット=同種・同言語のカード1〜set_size枚。

    1セット=1アップロード(=APIを1回消費)。運勢は必ず先頭の単独セット。
    残りは plan_today と同じ階層ラウンドロビンで案分し、各セットは1種類から
    まとめて数枚取る（言語は実行単位で固定なので混ざらない）。mbti_compat は
    品質ゲート(AUTO_MIN_SCORE)を通過したものだけが母集団になる。
    """
    import random

    sets: List[List[Dict[str, Any]]] = []
    if slots <= 0:
        return sets

    recent = _recent_ids(state, day)

    # 1) 運勢を最優先（ランキング＋主役star の2枚を1セット＝1本の動画に）
    fortune_cards = [c for c in _ensure_fortune_cards(lang, day, logger)
                     if c["id"] not in recent]
    if fortune_cards:
        sets.append(fortune_cards)

    # 2) 月末だけ、今月のポイント制ランキングを1本差し込む（2026年9月末から）
    if len(sets) < slots:
        monthly = _make_monthly_recap(lang, day, recent, logger)
        if monthly:
            sets.append([monthly])

    # 3) TOP3ランキングを複数セットにまとめる（星座ランキング軸を崩さない）
    if len(sets) < slots:
        used_now = {p["id"] for s in sets for p in s}
        topic_limit = max(0, (slots - len(sets)) * set_size)
        topic_cards = [c for c in _make_fortune_topic_candidates(lang, day, recent, logger, topic_limit)
                       if c["id"] not in used_now]
        order = {topic: i for i, topic in enumerate(FORTUNE_TOPIC_ORDER)}
        topic_cards.sort(key=lambda c: order.get(c.get("topic", ""), 999))
        for i in range(0, len(topic_cards), set_size):
            if len(sets) >= slots:
                break
            batch = topic_cards[i:i + set_size]
            if batch:
                sets.append(batch)

    # 3) 種類ごとのキュー（品質ゲート＋直近除外）を作り、毎回ランダムにシャッフル
    rnd = random.Random()  # 毎回ランダム（運要素を持たせる／日付で固定しない）
    used = {p["id"] for s in sets for p in s}
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    # その場で毎回ランダム生成する種類（在庫=jsonlからは拾わない）
    REGEN_KINDS = ("mbti_compat", "rank", "blood_order", "mbti_order")
    for r in _load_records(lang):
        k = r.get("kind")
        if (k == "fortune" or k in REGEN_KINDS
                or not _kind_allowed(lang, k)
                or r["id"] in recent or r["id"] in used):
            continue
        if not _auto_eligible(r):
            continue
        by_kind.setdefault(k, []).append(r)

    # mbti_compat: 核(型ペア)をランダム選択 → その場でルール生成（中身を差し替え）
    if _kind_allowed(lang, "mbti_compat"):
        try:
            compat = _make_compat_candidates(lang, day, recent, slots * set_size, logger)
            if compat:
                by_kind["mbti_compat"] = compat
        except Exception as e:
            logger.warning(f"相性カードの生成に失敗（在庫からの選択にフォールバック）: {e}")
            for r in _load_records(lang):
                if (r.get("kind") == "mbti_compat" and r["id"] not in recent
                        and r["id"] not in used and _auto_eligible(r)):
                    by_kind.setdefault("mbti_compat", []).append(r)

    # rank: テーマと並び順をランダムに決めて毎回生成（在庫キャッシュを避ける）
    if _kind_allowed(lang, "rank"):
        try:
            ranks = _make_rank_candidates(lang, day, recent, slots * set_size, logger)
            if ranks:
                by_kind["rank"] = ranks
        except Exception as e:
            logger.warning(f"ランキングの生成に失敗（このジャンルはスキップ）: {e}")

    # blood_order / mbti_order: 核(主軸×きょうだい順)をランダムに選んで毎回生成
    for genre, kind in (("blood", "blood_order"), ("mbti", "mbti_order")):
        if not _kind_allowed(lang, kind):
            continue
        try:
            combo = _make_combo_candidates(genre, lang, day, recent, slots * set_size, logger)
            if combo:
                by_kind[kind] = combo
        except Exception as e:
            logger.warning(f"組み合わせカード({kind})の生成に失敗（このジャンルはスキップ）: {e}")

    for k in by_kind:
        rnd.shuffle(by_kind[k])

    # 3) ジャンルを“重み付き・非復元”で抽選 → 1セット=1ジャンルから枠を埋める。
    #    「最初にジャンルを確率で選ぶ」方式。人気ジャンルほど当たりやすく、
    #    一巡するまで同じジャンルは出ないので、毎日の構成がきれいにまとまる。
    while len(sets) < slots and any(by_kind.get(k) for k in by_kind):
        avail = [k for k in by_kind if by_kind.get(k)]
        for k in _weighted_order(avail, rnd):
            if len(sets) >= slots:
                break
            q = by_kind.get(k)
            if not q:
                continue
            batch = [q.pop(0) for _ in range(min(set_size, len(q)))]
            if batch:
                sets.append(batch)

    return sets[:slots]


# =====================================================================
# レンダリング（HTML→PNG→mp4）
# =====================================================================
def render_html_to_png(html_rel: str, out_png: Path, logger: logging.Logger,
                       attempts: int = 3) -> bool:
    """HTML を Edge ヘッドレスで PNG に焼く。連続起動でたまに失敗するので数回リトライ。

    運勢は1セットで2枚（ランキング＋主役star）を続けて焼くため、Edge の同時起動が
    ぶつかって2枚目が落ちることがある。無人運用で取りこぼさないよう、出力が出るまで
    短い間隔で最大 attempts 回やり直す。
    """
    import time
    html_path = (RAG / html_rel).resolve()
    if not html_path.exists():
        logger.error(f"HTMLが見つかりません: {html_path}")
        return False
    configured = os.environ.get("CHROME_PATH", "").strip()
    browser = configured or next(
        (candidate for candidate in (
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("msedge"),
            WINDOWS_EDGE if Path(WINDOWS_EDGE).is_file() else None,
        ) if candidate),
        "",
    )
    if not browser or not Path(browser).is_file():
        logger.error("Chrome/Chromium/Edge が見つかりません。CHROME_PATH を設定してください。")
        return False
    for i in range(1, attempts + 1):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="edge_", dir=str(OUT_DIR),
                                         ignore_cleanup_errors=True) as edge_profile:
            cmd = [browser, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                   f"--user-data-dir={edge_profile}",
                   "--run-all-compositor-stages-before-draw", "--virtual-time-budget=3000",
                   "--force-device-scale-factor=1", "--window-size=1080,1920",
                   f"--screenshot={out_png.resolve()}", html_path.as_uri()]
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=60)
                if result.returncode != 0:
                    logger.warning(f"ブラウザレンダー終了コード={result.returncode} ({i}/{attempts})")
            except Exception as e:
                logger.warning(f"ブラウザレンダー失敗（{i}/{attempts}回目）: {e}")
        if out_png.exists():
            return True
        if i < attempts:
            time.sleep(1.0)
    logger.error(f"Edgeレンダーが{attempts}回とも失敗: {html_rel}")
    return False


def png_to_short_mp4(png: Path, out_mp4: Path, logger: logging.Logger) -> bool:
    """静止カードPNGを、ゆっくりズームのショート動画(mp4)に。"""
    try:
        from core.video_composer import VideoComposer
        vc = VideoComposer(total_seconds=SHORT_SECONDS, aspect="9:16", fps=30)
        video = vc.compose([{"path": str(png)}], effect="zoom")
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        # 無音の静止カード → libx264 veryfast（無人実行で堅実）
        video.write_videofile(
            str(out_mp4), fps=30, codec="libx264", preset="veryfast",
            audio=False, threads=4, logger=None,
        )
        return out_mp4.exists()
    except Exception as e:
        logger.error(f"mp4化に失敗: {e}")
        return False


# =====================================================================
# タイトル/概要欄/タグ（テンプレから決定的に・LLM不使用）
# =====================================================================
JA_ZODIAC_HASHTAGS = (
    "#星座占い",
    "#今日の運勢",
    "#12星座占い",
    "#星座ランキング",
    "#Shorts",
)

EN_ZODIAC_HASHTAGS = (
    "#ZodiacSigns",
    "#Astrology",
    "#Horoscope",
    "#ZodiacRanking",
    "#Shorts",
)


def _build_title(base: str) -> str:
    """YouTubeタイトル: 100字以内に丸め、収まれば末尾に ' #Shorts' を付ける。"""
    base = (base or "").strip()[:100].strip()
    if "#short" in base.lower():
        return base
    tag = " #Shorts"
    return (base + tag) if len(base) + len(tag) <= 100 else base


def _is_ja_zodiac_set(records: List[Dict[str, Any]], lang: str) -> bool:
    """日本語の毎日星座ランキング/TOP3だけを対象にする。"""
    if lang != "ja" or not records:
        return False
    return records[0].get("kind") in {"fortune", "fortune_topic"}


def _daily_ranking_top_sign(records: List[Dict[str, Any]]) -> str:
    """ランキングカードのフックから1位の星座名を取り出す。"""
    for record in records:
        item_id = str(record.get("id", ""))
        if (record.get("kind") == "fortune"
                and not item_id.endswith("_spot")):
            match = re.search(r"1位は([^！!？?\s]+)", str(record.get("hook", "")))
            if match:
                return match.group(1)
    return ""


def _remove_hashtags(text: str) -> str:
    """生成文中の旧タグを除き、固定タグとの重複を防ぐ。"""
    lines = []
    seen = set()
    for line in (text or "").splitlines():
        cleaned = re.sub(r"(?<!\S)#[^\s#]+", "", line).strip()
        dedupe_key = cleaned.lstrip("・").strip()
        if cleaned and dedupe_key not in seen:
            lines.append(cleaned)
            seen.add(dedupe_key)
    return "\n".join(lines).strip()


def _apply_ja_zodiac_metadata(meta: Dict[str, Any],
                              records: List[Dict[str, Any]],
                              day: date, lang: str) -> Dict[str, Any]:
    """日本語の星座動画に検索向け日付タイトルと固定5タグを適用する。"""
    if not _is_ja_zodiac_set(records, lang):
        return meta

    prefix = f"【{day.month}月{day.day}日】"
    top_sign = _daily_ranking_top_sign(records)
    if records[0].get("kind") == "fortune" and top_sign:
        title_base = f"{prefix}今日の12星座運勢ランキング｜1位は{top_sign}？"
    else:
        current = re.sub(r"^【\d{1,2}月\d{1,2}日】", "", meta.get("title", ""))
        current = re.sub(r"\s*#Shorts\s*$", "", current, flags=re.IGNORECASE).strip()
        title_base = f"{prefix}{current}"

    body = _remove_hashtags(meta.get("description", ""))
    parts = []
    if records[0].get("kind") == "fortune":
        parts.append(
            f"{day.year}年{day.month}月{day.day}日の12星座ランキングです。\n"
            "恋愛運・仕事運・金運など今日の運勢をチェック。"
        )
    if body:
        parts.append(body)
    parts.append(" ".join(JA_ZODIAC_HASHTAGS))

    return {
        "title": _build_title(title_base),
        "description": "\n\n".join(parts),
        "tags": [tag.lstrip("#") for tag in JA_ZODIAC_HASHTAGS],
    }


def _is_en_zodiac_set(records: List[Dict[str, Any]], lang: str) -> bool:
    """Limit English normalization to daily zodiac and zodiac-topic videos."""
    if lang != "en" or not records:
        return False
    return records[0].get("kind") in {"fortune", "fortune_topic"}


def _english_topic(records: List[Dict[str, Any]]) -> str:
    """Resolve a configured topic, with a text fallback for older records."""
    head = records[0]
    topic = str(head.get("topic", "")).strip().lower()
    if topic:
        return topic
    haystack = " ".join(
        str(head.get(key, "")) for key in ("id", "genre", "hook", "caption")
    ).lower()
    keyword_topics = (
        ("compatib", "compatibility"),
        ("red flag", "red_flags"),
        ("toxic trait", "toxic_traits"),
        ("love", "love"),
        ("money", "money"),
    )
    return next((topic for keyword, topic in keyword_topics if keyword in haystack), "")


def _without_just_for_fun(text: str) -> str:
    """Remove distancing boilerplate that is disallowed for English metadata."""
    cleaned = re.sub(r"\bjust\s+for\s+fun\b[.!]?", "", text or "",
                     flags=re.IGNORECASE)
    return "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())


def _apply_en_zodiac_metadata(meta: Dict[str, Any],
                              records: List[Dict[str, Any]],
                              day: date, lang: str) -> Dict[str, Any]:
    """Normalize English zodiac metadata after template or Ollama generation."""
    if not _is_en_zodiac_set(records, lang):
        return meta

    head = records[0]
    topic = _english_topic(records)
    cfg = _topic_config("en").get(topic, {})
    date_label = f"{calendar.month_name[day.month]} {day.day}"

    if head.get("kind") == "fortune":
        title_base = f"{date_label} Zodiac Signs Ranked | Who's #1 Today?"
        intro = (f"{calendar.month_name[day.month]} {day.day}, {day.year} daily "
                 "zodiac ranking. See where your sign lands today.")
        cta = "What's your sign?"
    else:
        title_template = str(cfg.get("youtube_title", ""))
        if title_template:
            title_base = title_template.format(date=date_label)
        else:
            genre = re.sub(r"\s*TOP\s*3\s*$", "", str(head.get("genre", "")),
                           flags=re.IGNORECASE).strip()
            genre = genre or "Zodiac Signs"
            title_base = f"{genre} Zodiac Ranking Today | {date_label}"
        intro = ""
        cta = str(cfg.get("cta", ""))

    is_negative = bool(cfg.get("negative"))
    if is_negative:
        # Do not trust free-form model copy for sensitive themes. Rebuild the
        # description from neutral deterministic language instead.
        if topic == "red_flags":
            body = "Today's ranking highlights temporary red-flag habits worth noticing."
        else:
            body = "Today's ranking highlights temporary tricky tendencies to keep in check."
    else:
        body = _without_just_for_fun(_remove_hashtags(meta.get("description", "")))

    parts = []
    if intro:
        parts.append(intro)
    if body:
        parts.append(body)
    if is_negative:
        parts.append("Every sign has its good side ✨")
    if cta:
        parts.append(cta)

    hashtags = list(EN_ZODIAC_HASHTAGS)
    theme_hashtag = str(cfg.get("theme_hashtag", "")).strip()
    if theme_hashtag and theme_hashtag.casefold() not in {
            tag.casefold() for tag in hashtags}:
        hashtags.append(theme_hashtag)
    parts.append(" ".join(hashtags))

    return {
        "title": _build_title(title_base),
        "description": "\n\n".join(parts),
        "tags": [tag.lstrip("#") for tag in hashtags],
    }


def _meta_from_record(r: Dict[str, Any]) -> Dict[str, Any]:
    title = _build_title(r.get("hook") or r.get("caption") or r.get("id"))
    tags = [t.lstrip("#") for t in (r.get("hashtags") or [])][:30]
    desc_lines = []
    if r.get("caption"):
        desc_lines.append(r["caption"])
    if r.get("hashtags"):
        desc_lines.append(" ".join(r["hashtags"]))
    description = "\n\n".join(desc_lines)
    return {"title": title, "description": description, "tags": tags}


def _meta_from_set(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """セット（1〜数枚）のタイトル/概要/タグ。先頭カードのフックを代表に。"""
    if len(records) == 1:
        return _meta_from_record(records[0])
    head = records[0]
    title = _build_title(head.get("hook") or head.get("caption") or head.get("id"))
    # 各カードのキャプションを箇条書きに
    desc_lines = [head.get("caption", "")] if head.get("caption") else []
    for r in records:
        cap = r.get("caption") or r.get("hook") or r.get("id")
        desc_lines.append(f"・{cap}")
    # タグはセット内で重複排除して集約
    seen, tags = set(), []
    for r in records:
        for t in (r.get("hashtags") or []):
            t = t.lstrip("#")
            if t and t not in seen:
                seen.add(t)
                tags.append(t)
    if tags:
        desc_lines.append(" ".join("#" + t for t in tags))
    return {"title": title, "description": "\n".join(desc_lines), "tags": tags[:30]}


def _meta_via_ollama(records: List[Dict[str, Any]], lang: str,
                     logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """Ollama でタイトル/説明/タグを生成（日本語/英語）。失敗/未起動なら None。

    手動メインタブと同じ `OllamaWriter.generate_package` を使う。テーマは先頭カードの
    hook と種類から組み立てる。無人実行を止めないため、例外も health 失敗も None を返し、
    呼び出し側でテンプレ（_meta_from_set）にフォールバックさせる。
    """
    try:
        import yaml
        from core.ollama_writer import OllamaWriter
        personal = {}
        pp = CONFIG_DIR / "personal.yaml"
        if pp.exists():
            personal = yaml.safe_load(pp.read_text(encoding="utf-8")) or {}
        ocfg = personal.get("ollama") or {}
        writer = OllamaWriter(host=ocfg.get("host", "http://localhost:11434"),
                              model=ocfg.get("default_model", "qwen3:14b"))
        if not writer.health():
            logger.info("Ollama 未起動 → テンプレ説明にフォールバック")
            return None
        head = records[0]
        kind = head.get("kind", "")
        hook = head.get("hook") or head.get("caption") or head.get("id", "")
        genre = ("星座占い / 今日の運勢ランキング / 恋愛運・金運・仕事運TOP3"
                 if lang == "ja"
                 else "daily zodiac ranking / horoscope TOP3 / encouraging action prompts")
        pkg = writer.generate_package(
            theme=f"{kind}: {hook}",
            platform="YouTube Shorts",
            genre=genre,
            overlay_hint=hook,
            lang=lang,
        )
        title = _build_title(pkg.get("title") or hook)
        tags = [str(t).lstrip("#") for t in (pkg.get("hashtags") or [])][:30]
        desc = pkg.get("description", "") or ""
        if not title.strip() or not desc.strip():
            return None
        logger.info("メタデータ: Ollama 生成を使用")
        return {"title": title, "description": desc, "tags": tags}
    except Exception as e:
        logger.warning(f"Ollama メタ生成に失敗（テンプレにフォールバック）: {e}")
        return None


def _build_meta(records: List[Dict[str, Any]], lang: str,
                use_ollama: bool, logger: logging.Logger,
                day: Optional[date] = None) -> Dict[str, Any]:
    """タイトル/説明/タグを作る。use_ollama 時は Ollama 優先、だめならテンプレ。"""
    meta = None
    if use_ollama:
        meta = _meta_via_ollama(records, lang, logger)
    if not meta:
        meta = _meta_from_set(records)
    metadata_day = day or date.today()
    meta = _apply_ja_zodiac_metadata(meta, records, metadata_day, lang)
    return _apply_en_zodiac_metadata(meta, records, metadata_day, lang)


def _record_set_upload(state: Dict[str, Any], day: date,
                       ids: List[str], video_url: str = "",
                       lang: str = "", channel: Optional[str] = None) -> None:
    """セットを1アップロードとして記録。countは全体、countsは言語/チャンネル別。"""
    key = day.isoformat()
    entry = state.setdefault(key, {"count": 0, "ids": [], "uploads": []})
    entry["count"] = int(entry.get("count", 0)) + 1
    scope = _state_scope(lang, channel)
    counts = entry.setdefault("counts", {})
    counts[scope] = int(counts.get(scope, 0)) + 1
    for i in ids:
        entry.setdefault("ids", []).append(i)
    entry.setdefault("uploads", []).append(
        {"id": ids[0], "ids": ids, "url": video_url,
         "lang": lang, "channel": channel or "",
         "at": datetime.now().isoformat(timespec="seconds")})
    _save_state(state)


def _is_daily_generated_card(card: Dict[str, Any], day: date) -> bool:
    cid = str(card.get("id", ""))
    kind = card.get("kind")
    if kind == "fortune_topic":
        return True
    if kind == "monthly_recap":
        return True
    if kind == "fortune":
        return (
            cid.startswith(f"fortune_{day.isoformat()}")
            or cid.startswith(f"fortune_en_{day.isoformat()}")
        )
    return False


def _remove_jsonl_ids(ids: set) -> None:
    if not ids or not JSONL.exists():
        return
    keep = []
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            keep.append(line)
            continue
        if row.get("id") not in ids:
            keep.append(line)
    JSONL.write_text(("\n".join(keep) + "\n") if keep else "", encoding="utf-8")


def _cleanup_set_artifacts(cards: List[Dict[str, Any]], day: date,
                           pngs: List[str], mp4: Optional[Path],
                           logger: logging.Logger) -> None:
    """Uploaded auto-generated media is disposable; keep state/YouTube URL, not files."""
    paths = [Path(p) for p in pngs]
    if mp4:
        paths.append(Path(mp4))
    remove_ids = set()
    for card in cards:
        if not _is_daily_generated_card(card, day):
            continue
        remove_ids.add(str(card.get("id", "")))
        html_rel = card.get("html")
        if html_rel:
            paths.append(RAG / html_rel)
        cid = str(card.get("id", ""))
        if cid:
            paths.append(IMG_DIR / f"{cid}.png")

    removed = 0
    for path in paths:
        try:
            rp = path.resolve()
            if not str(rp).startswith(str(ROOT.resolve())):
                continue
            if rp.exists() and rp.is_file():
                rp.unlink()
                removed += 1
        except Exception:
            continue
    try:
        _remove_jsonl_ids(remove_ids)
    except Exception as e:
        logger.warning(f"生成JSONLレコードの掃除に失敗（続行）: {e}")
    if removed:
        logger.info(f"アップ後の生成物を掃除: {removed} 件")


# =====================================================================
# 一時ファイルの掃除（毎回ランダム生成で増えるカードHTML/プレビューPNG）
# =====================================================================
import re as _re

# タイムスタンプ付き生成物（make_random が作る `*_<12桁以上>.html`）だけを対象に。
# 安定カタログ（rank_plan.html / blood_order_A_first.html / compat_INTJ_ENFP.html /
# eto_horse.html / birthday_1.html など）は末尾が12桁数字にならないので消えない。
_TS_HTML_RE = _re.compile(r"_\d{12,}\.html$")


def cleanup_temp_artifacts(max_age_hours: float = 48.0, logger=None) -> int:
    """毎回ランダム生成した一時HTML／プレビューPNGのうち、古いものを削除する。

    - data/rag/html: `*_<12桁以上>.html`（ランダム生成カードの一時HTML）
    - data/rag/images: `preview_*` / `compat_preview_*`（UIプレビューPNG）
    直近(max_age_hours以内)のものは触らない＝処理中のファイルは安全。戻り値=削除数。
    """
    import time
    cutoff = time.time() - max_age_hours * 3600.0
    removed = 0
    try:
        for p in (RAG / "html").glob("*.html"):
            try:
                if _TS_HTML_RE.search(p.name) and p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    except Exception:
        pass
    try:
        for p in (RAG / "images").glob("*.png"):
            try:
                if (p.name.startswith(("preview_", "compat_preview_"))
                        and p.stat().st_mtime < cutoff):
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    except Exception:
        pass
    if removed and logger:
        logger.info(f"一時ファイルを掃除: {removed} 件（{max_age_hours:.0f}h より古い生成物）")
    return removed


# 保持期間の既定値（自動掃除）。run_daily の冒頭で毎回呼ばれる。
LOG_RETENTION_DAYS = 30          # logs/auto_upload_*.log をこの日数で削除
BAT_LOG_MAX_BYTES = 1_000_000    # bat_last_run.log がこのサイズ超で末尾だけ残す
OUTPUT_RETENTION_DAYS = 14       # output/auto/<date>/ をこの日数で削除


def cleanup_logs(retention_days: int = LOG_RETENTION_DAYS,
                 bat_log_max_bytes: int = BAT_LOG_MAX_BYTES,
                 logger=None) -> int:
    """logs/ を掃除する。
    - auto_upload_YYYY-MM-DD.log: retention_days より古いものを削除
    - bat_last_run.log: 追記式で膨らむので、上限サイズ超なら末尾(最新)だけ残す
    戻り値=削除した日付ログ数。当日処理中のログ(_make_logger が掴むファイル)は
    mtime が新しいので触らない＝安全。
    """
    import time
    removed = 0
    cutoff = time.time() - retention_days * 86400.0
    try:
        for p in LOG_DIR.glob("auto_upload_*.log"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    except Exception:
        pass
    # bat_last_run.log を上限サイズで切り詰め（末尾＝最新ぶんだけ残す）
    try:
        bat = LOG_DIR / "bat_last_run.log"
        if bat.exists() and bat.stat().st_size > bat_log_max_bytes:
            keep = bat_log_max_bytes // 2
            data = bat.read_bytes()[-keep:]
            nl = data.find(b"\n")          # 行の途中で始まらないよう最初の改行で揃える
            if nl != -1:
                data = data[nl + 1:]
            bat.write_bytes(b"[older entries truncated to keep file small]\n" + data)
            if logger:
                logger.info(f"bat_last_run.log を切り詰め（>{bat_log_max_bytes}B）")
    except Exception:
        pass
    if removed and logger:
        logger.info(f"古いログを削除: {removed} 件（{retention_days}日より前）")
    return removed


def cleanup_old_outputs(retention_days: int = OUTPUT_RETENTION_DAYS,
                        logger=None) -> int:
    """output/auto/<YYYY-MM-DD>/ のうち retention_days より古い日付フォルダを削除。
    アップ済み判定は config の台帳(state)なので、動画を消しても二重投稿は起きない。
    日付以外の名前のフォルダ(_experiment 等)は対象外＝消さない。戻り値=削除フォルダ数。
    """
    import re
    import shutil
    removed = 0
    cutoff = date.today() - timedelta(days=retention_days)
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    try:
        for d in OUT_DIR.iterdir():
            if not d.is_dir() or not date_re.match(d.name):
                continue
            try:
                folder_day = datetime.strptime(d.name, "%Y-%m-%d").date()
            except ValueError:
                continue
            if folder_day < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    except FileNotFoundError:
        pass
    except Exception:
        pass
    if removed and logger:
        logger.info(f"古い出力フォルダを削除: {removed} 件（{retention_days}日より前）")
    return removed


# =====================================================================
# メイン: 毎朝のジョブ
# =====================================================================
def _auth_error_hint(e: Exception) -> str:
    """OAuth 例外を見て、無人実行ログに出す“次の一手”メッセージを作る。"""
    es = str(e)
    low = es.lower()
    if "invalid_grant" in low or "expired" in low or "revoked" in low:
        return ("YouTube認証トークンが期限切れ/失効しています（invalid_grant）。"
                "アプリのUI『➕ YouTubeチャンネルを接続 / 🔁 再ログイン』で再認証してください。"
                "※このOAuthアプリが『テスト中』のままだとトークンは7日で失効します。"
                "恒久対策はGoogle Cloud Consoleでアプリを『本番(Production)』に公開すること。")
    if "certificate" in low or "ssl" in low:
        return ("SSL証明書エラーで認証できません。ウイルス対策/社内プロキシのHTTPS検査を"
                "一時OFFにするか別回線で再認証してください。")
    return f"アップロード認証に失敗しました（OAuth/設定を確認）: {es}"


def _preflight_auth(uploader, logger: logging.Logger) -> None:
    """レンダー前に認証を1回だけ確認する。失敗時は例外を投げて run_daily に即中断させる。

    無人実行で「全部レンダーしてから毎件アップ失敗」を避けるための門番。check_auth を
    持たないアップローダ（テストのダミー等）はスキップする。
    """
    chk = getattr(uploader, "check_auth", None)
    if callable(chk):
        res = chk()  # チャンネル情報を1件取得（トークン期限切れならここで例外）
        if isinstance(res, dict) and not res.get("ok", True):
            raise RuntimeError(res.get("msg") or "チャンネル情報が取れませんでした")
        logger.info("認証プリフライト: OK")


def run_daily(max_uploads: int = DAILY_API_LIMIT, privacy: str = "public",
              channel: Optional[str] = None, lang: str = "en",
              dry_run: bool = False, use_ollama: bool = True,
              uploader_factory=None, quota_this_run: Optional[int] = None) -> Dict[str, Any]:
    """その日の残り枠ぶんを自動アップ。戻り値はサマリ dict。

    uploader_factory(channel_label) -> uploader（.upload を持つ）。None なら本物を遅延生成。
    dry_run=True ならアップロード直前まで全部やって、実投稿だけスキップ。
    quota_this_run を指定すると「この言語/チャンネルぶんの固定枠」になる。
    日英を別アカウント/別OAuthクライアントで運用するため、上限は言語別に見る。
    """
    channel = resolve_channel_for_lang(lang, channel)
    day = date.today()
    logger = _make_logger(day)
    logger.info("=" * 60)
    logger.info(f"自動アップ開始 lang={lang} privacy={privacy} channel={channel} "
                f"dry_run={dry_run} use_ollama={use_ollama}")

    # 毎回ランダム生成で増える一時HTML/プレビューPNGの古い分を掃除（48hより前）
    try:
        cleanup_temp_artifacts(48.0, logger)
    except Exception as e:
        logger.warning(f"一時ファイル掃除に失敗（続行）: {e}")
    # 溜まり続けるログ・古い出力動画も自動掃除（保持期間は上の定数で調整可）
    try:
        cleanup_logs(logger=logger)
    except Exception as e:
        logger.warning(f"ログ掃除に失敗（続行）: {e}")
    try:
        cleanup_old_outputs(logger=logger)
    except Exception as e:
        logger.warning(f"出力フォルダ掃除に失敗（続行）: {e}")

    state = _load_state()
    from core.shared_posting import shared_control
    control, observe_remote = shared_control()
    control.import_studio(CONFIG_DIR / "auto_upload_state.json")
    market = "US" if lang == "en" else "JP"
    allowance = control.status()[market]["remaining_by_app"]["studio"]
    done = uploaded_today(state, day, lang, channel)
    if quota_this_run is not None:
        # マルチ言語: この言語/チャンネルの固定枠。相手言語の投稿数に左右されない。
        slots = max(0, min(quota_this_run - done, DAILY_API_LIMIT - done, allowance))
        logger.info(f"本日アップ済み={done} / 固定枠={quota_this_run} / "
                    f"言語別上限={DAILY_API_LIMIT} → 今回枠={slots}")
    else:
        slots = max(0, min(min(max_uploads, DAILY_API_LIMIT) - done, allowance))
        logger.info(f"本日アップ済み={done} / 上限={min(max_uploads, DAILY_API_LIMIT)} → 残り枠={slots}")

    summary = {"date": day.isoformat(), "lang": lang, "channel": channel or "", "planned": 0,
               "uploaded": [], "skipped": [], "errors": [],
               "log": str(LOG_DIR / f"auto_upload_{day.isoformat()}.log")}

    if slots <= 0:
        logger.info("残り枠なし。終了。")
        return summary

    # ★認証プリフライト: 本番実行はレンダー前に1回だけ認証確認。トークン切れなら
    #   ここで即中断して「9本レンダーしてから全件アップ失敗」という無駄を防ぐ。
    uploader = None
    if not dry_run:
        try:
            uploader = (uploader_factory or _default_uploader_factory)(channel)
            _preflight_auth(uploader, logger)
            observe_remote(control, uploader._service_or_build(), market)
            slots = min(slots, control.status()[market]["remaining_by_app"]["studio"])
            if slots <= 0:
                return summary
        except Exception as e:
            hint = _auth_error_hint(e)
            logger.error(hint)
            summary["errors"].append({"stage": "auth", "error": str(e), "hint": hint})
            return summary

    # BGM（聴ける楽曲）が無ければ生成しておく
    try:
        from core.bgm_picker import ensure_music
        made = ensure_music(BGM_DIR)
        if made:
            logger.info(f"楽曲BGMを新規生成: {made}曲")
    except Exception as e:
        logger.warning(f"BGM準備に失敗（無音で続行する場合あり）: {e}")

    sets = plan_sets(lang, day, slots, state, logger)
    summary["planned"] = len(sets)
    plan_desc = "; ".join("+".join(p["id"] for p in s) for s in sets)
    logger.info(f"本日の計画 {len(sets)} セット: {plan_desc}")
    if not sets:
        logger.info("アップ候補なし（直近で出し切り？）。終了。")
        return summary

    work = OUT_DIR / day.isoformat()
    for si, cards in enumerate(sets):
        ids = [c["id"] for c in cards]
        set_id = ids[0]
        pngs: List[str] = []
        mp4: Optional[Path] = None
        reservation = None
        try:
            # 各カードをPNG化
            for c in cards:
                png = work / f"{c['id']}.png"
                png.parent.mkdir(parents=True, exist_ok=True)
                if render_html_to_png(c["html"], png, logger):
                    pngs.append(str(png))
                else:
                    logger.warning(f"[{c['id']}] レンダー失敗 → このカードは除外")
            if not pngs:
                summary["skipped"].append({"id": set_id, "reason": "render_failed"})
                continue

            # BGMを“一様ランダム”で選曲（どの曲も等確率＝偏らない／毎回ちがう）
            bgm = None
            try:
                from core.bgm_picker import pick as pick_bgm, DEFAULT_AUTO_VOLUME
                bgm = pick_bgm(BGM_DIR, seed=None, uniform=True)
                bgm_vol = DEFAULT_AUTO_VOLUME
            except Exception as e:
                logger.warning(f"BGM選曲に失敗（無音で続行）: {e}")
                bgm_vol = 0.18

            mp4 = work / f"{set_id}__set{len(pngs)}.mp4"
            from core.card_video import build_card_video
            ok = build_card_video(pngs, str(mp4), bgm_path=bgm, volume=bgm_vol,
                                  seconds_per_card=SECONDS_PER_CARD, logger=logger)
            if not ok:
                summary["skipped"].append({"id": set_id, "reason": "encode_failed"})
                continue

            meta = _build_meta(cards, lang, use_ollama, logger, day=day)
            bgm_name = Path(bgm).name if bgm else "（無音）"
            logger.info(f"[{set_id}] セット{len(pngs)}枚 動画OK BGM={bgm_name} "
                        f"→ アップ: title='{meta['title']}'")

            if dry_run:
                logger.info(f"[{set_id}] DRY-RUN: 実投稿はスキップ（mp4={mp4}）")
                summary["uploaded"].append({"id": set_id, "ids": ids,
                                            "url": "(dry-run)", "mp4": str(mp4)})
                continue

            try:
                reservation = control.reserve("studio", market, set_id)
            except RuntimeError as exc:
                if type(exc).__name__ != 'AllowanceUnavailable':
                    raise
                logger.info('Shared allowance is occupied; waiting for the next run.')
                summary['skipped'].append({'id': set_id, 'reason': 'waiting_for_allowance'})
                break
            res = uploader.upload(
                video_path=str(mp4), title=meta["title"],
                description=meta["description"], tags=meta["tags"],
                privacy=privacy, is_short=True, made_for_kids=False,
            )
            url = res.get("url", "")
            vid = res.get("video_id") or res.get("id") or url.rsplit("/", 1)[-1].split("?")[0]
            control.commit(reservation, vid)
            logger.info(f"[{set_id}] アップ完了: {url}")
            _record_set_upload(state, day, ids, url, lang=lang, channel=channel)
            summary["uploaded"].append({"id": set_id, "ids": ids, "url": url})
        except Exception as e:
            if reservation:
                control.uncertain(reservation)
            logger.exception(f"[{set_id}] 失敗: {e}")
            summary["errors"].append({"id": set_id, "error": str(e)})
        finally:
            if not dry_run:
                _cleanup_set_artifacts(cards, day, pngs, mp4, logger)

    logger.info(f"完了: アップ {len(summary['uploaded'])} / 計画 {len(sets)} / "
                f"エラー {len(summary['errors'])}")
    logger.info("=" * 60)
    return summary


def _default_uploader_factory(channel: Optional[str]):
    """本番アップローダを config から組み立てる（遅延importで重さ回避）。"""
    import yaml
    from core.youtube_uploader import YouTubeUploader
    from core.channel_manager import ChannelManager

    personal = {}
    pp = CONFIG_DIR / "personal.yaml"
    if pp.exists():
        personal = yaml.safe_load(pp.read_text(encoding="utf-8")) or {}
    cm = ChannelManager(CONFIG_DIR)
    labels = cm.list_labels()
    label = channel or (labels[0] if labels else None)
    if not label:
        raise RuntimeError("アップロード先チャンネル（トークン）がありません。OAuthログインが必要です。")
    default_client_secret = (personal.get("youtube_api", {}) or {}).get("client_secret_path", "")
    client_secret_path = cm.client_secret_path(label, default_client_secret)
    if not client_secret_path or not client_secret_path.exists():
        raise FileNotFoundError(f"client_secret.json が未設定です（channel={label}）")
    token_path = cm.token_path(label)
    if not token_path.exists():
        raise RuntimeError(f"アップロード先チャンネル `{label}` のOAuthトークンがありません。先に再ログインしてください。")
    return YouTubeUploader(str(client_secret_path), str(token_path))


if __name__ == "__main__":  # 簡易手動テスト（dry-run）
    import pprint
    pprint.pprint(run_daily(max_uploads=3, lang="en", dry_run=True))

# -*- coding: utf-8 -*-
"""
今日の運勢スポットライト文の生成（Ollama → RAG文言バンクのフォールバック）
==========================================================================
1位の星座（今日の主役）について、総合・恋愛・仕事・金運・ラッキーカラー/アイテム・
ひとことアドバイスを返す。

方針（無人運用で“絶対に止めない”）:
  - Ollama 起動時は LLM で当日の文を生成（日本語/英語）。
  - 未起動・例外・タイムアウト・空応答のいずれでも、必ず RAG 文言バンク
    (data/rag/knowledge/fortune_phrases_<lang>.json) から決定的に組み立てて返す。
  - 日付×星座コードでシードするので「同じ日付なら同じ結果」（再現性あり）。

返り値の dict キー: overall / love / work / money / color / item / advice
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
KN = ROOT / "data" / "rag" / "knowledge"
CONFIG_DIR = ROOT / "config"

_CATS = ("overall", "love", "work", "money")


def _tier(rank: int) -> str:
    if rank <= 3:
        return "top"
    if rank <= 6:
        return "high"
    if rank <= 9:
        return "mid"
    return "low"


def _rng(day: date, code: str) -> random.Random:
    seed = int(hashlib.md5(f"{day.isoformat()}:{code}".encode("utf-8")).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def _load_bank(lang: str) -> Dict[str, Any]:
    path = KN / (f"fortune_phrases_en.json" if lang == "en" else "fortune_phrases_ja.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _spotlight_from_bank(sign: Dict[str, Any], rank: int, day: date, lang: str) -> Dict[str, str]:
    """RAG 文言バンクから決定的に組み立てる（Ollama 不在時のフォールバック）。"""
    bank = _load_bank(lang)
    tier = _tier(rank)
    rnd = _rng(day, sign.get("code", "") + ":spot")

    def pick_tier(cat: str) -> str:
        pools = bank.get(cat, {})
        pool = pools.get(tier) or pools.get("top") or []
        return rnd.choice(pool) if pool else ""

    return {
        "overall": pick_tier("overall"),
        "love": pick_tier("love"),
        "work": pick_tier("work"),
        "money": pick_tier("money"),
        "advice": rnd.choice(bank.get("advice") or [""]),
        "color": rnd.choice(bank.get("colors") or [(sign.get("lucky") or {}).get("color", "")]),
        "item": rnd.choice(bank.get("items") or [(sign.get("lucky") or {}).get("item", "")]),
    }


def _ollama_prompt(sign: Dict[str, Any], rank: int, lang: str) -> tuple[str, str]:
    name = sign.get("name", "")
    traits = sign.get("traits", "")
    if lang == "en":
        system = ("You write short, warm, believable daily horoscope copy. "
                  "Output STRICT JSON only, no markdown, no commentary. English only.")
        user = f"""Write today's lucky-sign spotlight for the No.{rank} sign of a daily zodiac ranking.

Sign: {name}
Sign personality (for flavor, do not copy verbatim): {traits}

Tone: positive, encouraging, specific enough to feel personal but universal (Barnum-style).
Each field is ONE short sentence (<= 70 chars), no emoji.

Output a JSON object with EXACTLY these keys:
{{
  "overall": "<overall luck for today>",
  "love": "<love luck for today>",
  "work": "<work luck for today>",
  "money": "<money luck for today>",
  "advice": "<one gentle piece of advice>",
  "color": "<a lucky color, 1-2 words>",
  "item": "<a lucky item, 1-3 words>"
}}
Respond with ONLY the JSON."""
    else:
        system = ("あなたは、短くあたたかく“当てはまり感”のある今日の運勢を書くプロです。"
                  "出力は厳密なJSONのみ。マークダウンや前置きは禁止。日本語で書くこと。")
        user = f"""今日の運勢ランキングで1位（今日の主役）の星座について、スポットライト文を書いてください。

星座: {name}
星座の性格（雰囲気づくり用。そのまま写さない）: {traits}

トーン: 前向きで応援的。具体的だけど誰にでも当てはまる占い調（バーナム効果）。
各項目は1文・短め（35字以内）・絵文字なし。

次のキーだけを持つJSONオブジェクトを出力:
{{
  "overall": "<今日の総合運>",
  "love": "<今日の恋愛運>",
  "work": "<今日の仕事運>",
  "money": "<今日の金運>",
  "advice": "<ひとことアドバイス>",
  "color": "<ラッキーカラー・1〜2語>",
  "item": "<ラッキーアイテム・1〜4語>"
}}
JSONのみで答えてください。"""
    return system, user


def _spotlight_via_ollama(sign: Dict[str, Any], rank: int, lang: str) -> Optional[Dict[str, str]]:
    """Ollama でスポットライト文を生成。未起動・例外・空応答なら None。"""
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
            return None
        system, user = _ollama_prompt(sign, rank, lang)
        raw = writer._chat(system, user, temperature=0.85, timeout=120)
        obj = OllamaWriter._parse_json(raw)
        keys = ("overall", "love", "work", "money", "advice", "color", "item")
        out = {k: str(obj.get(k, "")).strip() for k in keys}
        # 必須カテゴリが欠けていたら失敗扱い（フォールバックさせる）
        if not all(out[k] for k in ("overall", "love", "work", "money")):
            return None
        return out
    except Exception:
        return None


def fortune_spotlight(sign: Dict[str, Any], rank: int, day: date, lang: str,
                      use_ollama: bool = True) -> Dict[str, str]:
    """1位の星座のスポットライト文を返す。Ollama→バンクの順。必ず全フィールドを埋める。"""
    base = _spotlight_from_bank(sign, rank, day, lang)
    if use_ollama:
        llm = _spotlight_via_ollama(sign, rank, lang)
        if llm:
            # 欠けたフィールドはバンクで補完（color/item は空なら星座の定番→バンク）
            for k, v in base.items():
                if not llm.get(k):
                    llm[k] = v
            return llm
    return base

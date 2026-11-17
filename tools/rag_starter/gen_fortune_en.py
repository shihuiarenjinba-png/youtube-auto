# -*- coding: utf-8 -*-
"""
Today's Zodiac Luck Ranking (English, morning-TV style)
========================================================
Shuffles the Western 12 signs deterministically by date seed into a 1-12
ranking card, renders it to PNG via headless Edge, and adds a short REASON
for every rank plus a "Today's Power Pair" (lucky combo) with its own reason.

- Same date -> same result (reproducible): one auto-generated clip per day.
- Usage: .venv/Scripts/python.exe tools/rag_starter/gen_fortune_en.py [YYYY-MM-DD]
"""
from __future__ import annotations
import json, random, subprocess, sys, hashlib, tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # import core.fortune_writer
from core.zodiac_balance import balanced_daily_order
KN = ROOT / "data" / "rag" / "knowledge"
TPL = (ROOT / "data" / "rag" / "templates" / "ranking_en.html").read_text(encoding="utf-8")
SPOT_TPL = (ROOT / "data" / "rag" / "templates" / "fortune_spotlight_en.html").read_text(encoding="utf-8")
HTML_DIR = ROOT / "data" / "rag" / "html"
IMG_DIR = ROOT / "data" / "rag" / "images"
HTML_DIR.mkdir(parents=True, exist_ok=True)
EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

ZSYM = {"aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋",
        "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏",
        "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓"}
MEDAL = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LUCKY_ITEM = ["coffee", "a blue pen", "a handkerchief", "a lucky charm", "music",
              "something sweet", "a green plant", "a white shirt", "a notebook",
              "fresh socks", "aromatherapy", "an old photo",
              "a warm cup of tea", "a small flower", "a favorite book",
              "a silver accessory", "a lemon", "a candle", "a hint of mint", "a letter"]

# Reason pools per rank tier. Keep the wording graceful and polite.
# {r} = ruling planet, {e} = element.
R_TOP = ["{r} is fully on your side today.", "Your {e} energy is shining brightly.",
         "Whatever you begin falls neatly into place today.",
         "The stars align gracefully in your favor.",
         "A bold, sincere move pays off beautifully.",
         "Good fortune flows your way with ease.",
         "Your efforts blossom into something wonderful."]
R_HIGH = ["{r} offers you a gentle push forward.", "Your {e} flow stays smooth and steady.",
          "A small, careful step lands exactly right.",
          "Warm energy follows you throughout the day.",
          "A kind word quietly opens the right door.",
          "Thoughtful choices bring steady progress.",
          "A pleasant encounter lifts your spirits."]
R_MID = ["Keep your own pace and your {e} stays balanced.",
         "A calm day to gently recharge yourself.",
         "A grateful heart lifts your luck a notch.",
         "No need to rush; simply keep things in order.",
         "A short rest sets up your next bright spell.",
         "Honoring a small promise builds quiet trust.",
         "Stay composed and your rhythm returns naturally."]
R_LOW = ["{r} gently asks you to slow down today.",
         "Play it safe and you will be perfectly fine.",
         "Breathe deeply and let nothing rush you.",
         "Listen more than you speak, and things go smoothly.",
         "Notice the small blessings right in front of you.",
         "Take a quiet moment to care for yourself.",
         "One calm step at a time prepares you for tomorrow."]


def _sign_rng(day: date, code: str) -> random.Random:
    """Per-sign, date-fixed RNG so each sign's reason is independent yet reproducible."""
    s = int(hashlib.md5(f"{day.isoformat()}:{code}".encode()).hexdigest(), 16) % (2**32)
    return random.Random(s)


def reason(rank, sign, rnd):
    """Rank-tier tone, sometimes swapped for the sign's own one-liner (personality flavor)."""
    pool = R_TOP if rank <= 3 else R_HIGH if rank <= 6 else R_MID if rank <= 9 else R_LOW
    if sign.get("oneline") and rnd.random() < 0.34:
        return sign["oneline"]
    return rnd.choice(pool).format(r=sign.get("ruler", ""), e=sign.get("element", ""))


def pair_reason(e1, e2):
    a, b = sorted([e1, e2])
    if e1 == e2:
        return f"Two {e1} signs amplify each other's energy."
    pairs = {
        ("Air", "Fire"): "Fire and Air fan each other into something bigger.",
        ("Earth", "Water"): "Earth and Water nourish and ground each other.",
        ("Air", "Earth"): "Air's ideas meet Earth's follow-through perfectly.",
        ("Fire", "Water"): "Fire's spark and Water's depth make a magnetic mix.",
        ("Air", "Water"): "Air lifts the mood while Water adds real heart.",
        ("Earth", "Fire"): "Earth steadies Fire's drive into solid results.",
    }
    return pairs.get((a, b), "Your rhythms just fit, and today it shows.")


def build(day: date):
    data = json.loads((KN / "zodiac_en.json").read_text(encoding="utf-8"))
    signs = data["signs"]
    name_by = {s["code"]: s["name"] for s in signs}
    elem_by = {s["code"]: s["element"] for s in signs}
    ruler_by = {s["code"]: s["ruler"] for s in signs}
    compat_by = {s["code"]: s["compat"]["best"] for s in signs}

    seed = int(hashlib.md5(day.isoformat().encode()).hexdigest(), 16) % (2**32)
    order = balanced_daily_order(signs, day)

    rows = []
    for i, s in enumerate(order, start=1):
        cls = "item top" if i <= 3 else "item"
        rank_html = (f'<div class="medal">{MEDAL[i]}</div>' if i in MEDAL
                     else f'<div class="rank">No.{i}</div>')
        srnd = _sign_rng(day, s["code"])
        rs = reason(i, s, srnd)
        if i <= 3:
            item = LUCKY_ITEM[(seed + i) % len(LUCKY_ITEM)]
            rs = f'{rs} Lucky: {item}'
        rows.append(
            f'<div class="{cls}">{rank_html}'
            f'<div class="sym">{ZSYM.get(s["code"], "★")}</div>'
            f'<div class="nm">{s["name"]}</div>'
            f'<div class="cm">{rs}</div></div>')

    top = order[0]
    rank_index = {s["code"]: idx for idx, s in enumerate(order)}
    partners = sorted(compat_by[top["code"]], key=lambda c: rank_index.get(c, 99))
    partner = partners[0] if partners else order[1]["code"]
    combo = f'{top["name"]} x {name_by.get(partner, partner)}'
    combo_sub = pair_reason(elem_by[top["code"]], elem_by.get(partner, top["element"]))

    wd = WEEK[day.weekday()]
    date_str = f'{wd}, {MONTHS[day.month - 1]} {day.day}, {day.year}'

    html = TPL
    for k, v in {"{{DATE}}": date_str, "{{ROWS}}": "".join(rows),
                 "{{COMBO}}": combo, "{{COMBO_SUB}}": combo_sub}.items():
        html = html.replace(k, v)
    out_html = HTML_DIR / f'fortune_en_{day.isoformat()}.html'
    out_html.write_text(html, encoding="utf-8")

    rank_lines = "\n".join(f'No.{i} {name_by[order[i-1]["code"]]}' for i in range(1, 13))
    rec = {
        "id": f'fortune_en_{day.isoformat()}', "genre": "Daily Zodiac Ranking",
        "format": "ranking card HTML", "kind": "fortune", "lang": "en",
        "html": f'html/fortune_en_{day.isoformat()}.html',
        "hook": f'{date_str} - 12 Zodiac luck ranking! No.1 is {top["name"]}',
        "caption": "Where does your sign rank today? Plus today's power pair!",
        "hashtags": ["#horoscope", "#zodiac", "#ranking", "#shorts"],
        "ft": {
            "instruction": "Write a short-form daily 12-zodiac luck ranking script",
            "input": f'{date_str} No.1={top["name"]} power pair={combo}',
            "output": (f"[Hook] {date_str} - today's zodiac luck ranking! Where are you?\n"
                       f'[Ranking]\n{rank_lines}\n'
                       f'[Power pair] Today\'s luckiest duo is {combo}! {combo_sub}\n'
                       f'[Close] No.1 is {top["name"]}! Comment your rank below.')
        }
    }

    # Card 2: spotlight on today's No.1 sign (overall/love/work/money/lucky/advice)
    spot_html, spot_rec = build_spotlight(day, top, date_str)
    return [(out_html.name, rec), (spot_html, spot_rec)]


def build_spotlight(day: date, top: dict, date_str: str):
    """Detailed card for today's No.1 sign. Body via Ollama when up, else RAG bank
    (core.fortune_writer guarantees the fallback so it never comes back empty)."""
    from core.fortune_writer import fortune_spotlight
    sp = fortune_spotlight(top, 1, day, lang="en")

    html = SPOT_TPL
    for k, v in {"{{DATE}}": date_str, "{{SYM}}": ZSYM.get(top["code"], "★"),
                 "{{NAME}}": top["name"], "{{OVERALL}}": sp["overall"],
                 "{{LOVE}}": sp["love"], "{{WORK}}": sp["work"],
                 "{{MONEY}}": sp["money"], "{{ADVICE}}": sp["advice"],
                 "{{COLOR}}": sp["color"], "{{ITEM}}": sp["item"]}.items():
        html = html.replace(k, v)
    out_html = HTML_DIR / f'fortune_en_{day.isoformat()}_spot.html'
    out_html.write_text(html, encoding="utf-8")

    rec = {
        "id": f'fortune_en_{day.isoformat()}_spot', "genre": "Today's Star",
        "format": "fortune spotlight HTML", "kind": "fortune", "lang": "en",
        "html": f'html/fortune_en_{day.isoformat()}_spot.html',
        "hook": f'{date_str} - Today\'s star is {top["name"]}! Love, work & money',
        "caption": f'{top["name"]}\'s overall, love, work, money luck and lucky picks for today!',
        "hashtags": ["#horoscope", "#zodiac", f'#{top["name"]}', "#shorts"],
        "ft": {
            "instruction": "Write a short-form spotlight horoscope script for today's No.1 sign",
            "input": f'{date_str} star={top["name"]} overall={sp["overall"]}',
            "output": (f'[Hook] Today\'s star is {top["name"]}!\n'
                       f'[Overall] {sp["overall"]}\n[Love] {sp["love"]}\n'
                       f'[Work] {sp["work"]}\n[Money] {sp["money"]}\n'
                       f'[Lucky] color {sp["color"]}, item {sp["item"]}\n'
                       f'[Close] {sp["advice"]}')
        }
    }
    return out_html.name, rec


def render_png(html_name, png_name, attempts=3):
    import time
    html_path = (HTML_DIR / html_name).resolve()
    png_path = (IMG_DIR / png_name).resolve()
    for i in range(attempts):
        cmd = [EDGE, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
               f"--user-data-dir={tempfile.mkdtemp(prefix='edge_')}",
               "--run-all-compositor-stages-before-draw", "--virtual-time-budget=3000",
               "--force-device-scale-factor=1", "--window-size=1080,1920",
               f"--screenshot={png_path}", html_path.as_uri()]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception:
            pass
        if png_path.exists():
            return True
        if i < attempts - 1:
            time.sleep(1.0)
    return png_path.exists()


def main():
    if len(sys.argv) > 1:
        day = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        day = date.today()
    cards = build(day)  # [(html_name, rec), ...] ranking + spotlight
    for html_name, rec in cards:
        print(f"EN fortune HTML -> {HTML_DIR / html_name}")

    jsonl = ROOT / "data" / "rag" / "examples.jsonl"
    new_ids = {rec["id"] for _, rec in cards}
    existing = jsonl.read_text(encoding="utf-8") if jsonl.exists() else ""
    keep = [l for l in existing.splitlines()
            if l.strip() and not any(f'"id": "{i}"' in l for i in new_ids)]
    with open(jsonl, "w", encoding="utf-8") as f:
        for l in keep:
            f.write(l + "\n")
        for _, rec in cards:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    for html_name, _ in cards:
        png = html_name[:-5] + ".png"  # fortune_en_<date>(_spot).html → .png
        ok = render_png(html_name, png)
        print(("  PNG OK " if ok else "  PNG NG ") + png)


if __name__ == "__main__":
    main()

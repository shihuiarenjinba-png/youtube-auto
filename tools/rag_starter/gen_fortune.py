# -*- coding: utf-8 -*-
"""
今日の運勢ランキング生成（めざまし風 12星座ランキング）
=========================================================
zodiac.json の12星座を、日付シードで決定的に並べ替えて 1〜12位の
ランキングカードHTMLを作り、Edge ヘッドレスで PNG に焼く。
さらに「今日の最強相性ペア」（ラッキーな組み合わせ）を下部に表示。

- 同じ日付なら毎回同じ結果（再現性あり）。
- 使い方: .venv/Scripts/python.exe tools/rag_starter/gen_fortune.py [YYYY-MM-DD]
"""
from __future__ import annotations
import json, random, subprocess, sys, hashlib, tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # core.fortune_writer を import するため
from core.zodiac_balance import balanced_daily_order
KN = ROOT / "data" / "rag" / "knowledge"
TPL = (ROOT / "data" / "rag" / "templates" / "ranking.html").read_text(encoding="utf-8")
SPOT_TPL = (ROOT / "data" / "rag" / "templates" / "fortune_spotlight.html").read_text(encoding="utf-8")
HTML_DIR = ROOT / "data" / "rag" / "html"
IMG_DIR = ROOT / "data" / "rag" / "images"
HTML_DIR.mkdir(parents=True, exist_ok=True)
EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

ZSYM = {"aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋", "leo": "♌",
        "virgo": "♍", "libra": "♎", "scorpio": "♏", "sagittarius": "♐",
        "capricorn": "♑", "aquarius": "♒", "pisces": "♓"}
MEDAL = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}

# 順位帯ごとの一言コメント（オリジナル）。シードで選択。
# 運勢は言葉づかいを丁寧に揃え、品のある表現を心がける。
CM_TOP = ["絶好調！動くほど運が味方してくれる一日です。",
          "迷わず進んで大正解。流れはあなたの味方です。",
          "重ねてきた努力が、一気に実を結ぶ最高の流れです。",
          "新しい出会いとチャンスの予感に満ちた一日。",
          "今日の主役はあなた。自信を持って前へ進みましょう。",
          "願いごとが叶いやすい、特別に恵まれた運気です。",
          "ひらめきが冴え、行動がそのまま成果につながります。"]
CM_HIGH = ["良い波に乗って、気持ちよく過ごせそうな一日です。",
           "ひと押しで物事が前へ進む、追い風の流れです。",
           "あなたの笑顔が、自然と幸運を呼び込みます。",
           "丁寧なふるまいが、まわりからきちんと評価されます。",
           "小さな挑戦が、思いがけない吉に変わる一日。",
           "人とのご縁に恵まれ、心あたたまる出来事がありそう。",
           "落ち着いた判断が、確かな前進をもたらします。"]
CM_MID = ["焦らず、自分のペースを保つことが正解です。",
          "いつも通りに過ごせば、十分にうまくいく一日。",
          "まわりへの感謝の気持ちが、運気をそっと押し上げます。",
          "無理をせず、身のまわりを整える穏やかな日に。",
          "ひと休みが、次の好調へとつながっていきます。",
          "小さな約束を守ることで、信頼が静かに育ちます。",
          "心を落ち着けて過ごせば、自然と調子が戻ります。"]
CM_LOW = ["慎重に歩みを進めれば、心配はいりません。",
          "今日は守りを大切に、こつこつと積み重ねる日。",
          "深呼吸をして、焦らずに過ごしてみましょう。",
          "聞き役にまわると、物事が穏やかに運びます。",
          "足もとの小さな幸せに、目を向けてみてください。",
          "ひと息ついて、自分をいたわる時間を大切に。",
          "あわてず一歩ずつ。明日への備えを整える日です。"]
LUCKY_ITEM = ["コーヒー", "青いペン", "ハンカチ", "お守り", "音楽", "甘いもの",
              "観葉植物", "白いシャツ", "手帳", "新しい靴下", "アロマ", "写真",
              "あたたかいお茶", "小さな花", "お気に入りの本", "シルバーの小物",
              "レモン", "キャンドル", "ミントの香り", "手紙"]


def _sign_rng(day: date, code: str) -> random.Random:
    """星座ごとに独立した（日付で固定の）乱数。順位帯コメントを星座別に決める。"""
    s = int(hashlib.md5(f"{day.isoformat()}:{code}".encode()).hexdigest(), 16) % (2**32)
    return random.Random(s)


def comment(rank, sign, rnd):
    """順位帯トーン＋その星座の性格（oneline）を織り交ぜた一言。星座別シードで決定的。"""
    pool = CM_TOP if rank <= 3 else CM_HIGH if rank <= 6 else CM_MID if rank <= 9 else CM_LOW
    # 1/3 の確率でその星座らしい一言（oneline）を採用 → 性格に寄せた当てはまり感を出す
    if sign.get("oneline") and rnd.random() < 0.34:
        return sign["oneline"]
    return rnd.choice(pool)


def build(day: date):
    """ランキングカードとスポットライトカードの (html_name, rec) を順に返す。"""
    data = json.loads((KN / "zodiac.json").read_text(encoding="utf-8"))
    signs = data["signs"]
    name_by = {s["code"]: s["name"] for s in signs}
    compat_by = {s["code"]: s["compat"]["best"] for s in signs}

    seed = int(hashlib.md5(day.isoformat().encode()).hexdigest(), 16) % (2**32)
    order = balanced_daily_order(signs, day)

    rows = []
    for i, s in enumerate(order, start=1):
        rank_disp = MEDAL.get(i)
        cls = "item top" if i <= 3 else "item"
        rank_html = (f'<div class="medal">{rank_disp}</div>' if rank_disp
                     else f'<div class="rank">{i}位</div>')
        srnd = _sign_rng(day, s["code"])
        cm = comment(i, s, srnd)
        item = LUCKY_ITEM[(seed + i) % len(LUCKY_ITEM)]
        cm_full = f'{cm}　ラッキー：{item}' if i <= 3 else cm
        rows.append(
            f'<div class="{cls}">{rank_html}'
            f'<div class="sym">{ZSYM.get(s["code"], "★")}</div>'
            f'<div class="nm">{s["name"]}</div>'
            f'<div class="cm">{cm_full}</div></div>')

    top = order[0]
    # 最強相性ペア = 1位の星座 × その相性ベストのうち上位にいる方
    rank_index = {s["code"]: idx for idx, s in enumerate(order)}
    partners = sorted(compat_by[top["code"]], key=lambda c: rank_index.get(c, 99))
    partner = partners[0] if partners else order[1]["code"]
    combo = f'{top["name"]} × {name_by.get(partner, partner)}'
    combo_sub = "この2人が一緒だと、今日はとびきりツイてる！"

    wd = "月火水木金土日"[day.weekday()]
    date_str = f'{day.month}月{day.day}日（{wd}）'

    html = TPL
    for k, v in {"{{DATE}}": date_str, "{{ROWS}}": "".join(rows),
                 "{{COMBO}}": combo, "{{COMBO_SUB}}": combo_sub}.items():
        html = html.replace(k, v)

    out_html = HTML_DIR / f'fortune_{day.isoformat()}.html'
    out_html.write_text(html, encoding="utf-8")

    # ランキングの台本（ft）
    rank_lines = "\n".join(
        f'{i}位 {name_by[order[i-1]["code"]]}' for i in range(1, 13))
    rec = {
        "id": f'fortune_{day.isoformat()}', "genre": "今日の運勢ランキング",
        "format": "ランキングカードHTML", "kind": "fortune",
        "html": f'html/fortune_{day.isoformat()}.html',
        "hook": f'{date_str} 12星座ランキング！1位は{order[0]["name"]}',
        "caption": "今日のあなたの運勢は何位？最強相性ペアも発表！",
        "hashtags": ["#今日の運勢", "#星座占い", "#ランキング", "#shorts"],
        "ft": {
            "instruction": "今日の運勢12星座ランキングのショート台本を作って",
            "input": f'{date_str} 1位={order[0]["name"]} 最強相性={combo}',
            "output": (f'【フック】{date_str}、今日の運勢ランキング発表！あなたは何位？\n'
                       f'【ランキング】\n{rank_lines}\n'
                       f'【最強相性】今日いちのラッキーペアは {combo}！\n'
                       f'【締め】1位は{order[0]["name"]}！何位だったかコメントで教えてね')
        }
    }

    # 2枚目: 今日の主役（1位）のスポットライト詳細カード
    spot_html, spot_rec = build_spotlight(day, top, date_str)
    return [(out_html.name, rec), (spot_html, spot_rec)]


def build_spotlight(day: date, top: dict, date_str: str):
    """1位の星座の詳細カード（総合/恋愛/仕事/金運/ラッキー/アドバイス）を作る。

    本文は Ollama 起動時は LLM、未起動時は RAG文言バンクから決定的に生成
    （core.fortune_writer がフォールバックを保証する）。
    """
    from core.fortune_writer import fortune_spotlight
    sp = fortune_spotlight(top, 1, day, lang="ja")

    html = SPOT_TPL
    for k, v in {"{{DATE}}": date_str, "{{SYM}}": ZSYM.get(top["code"], "★"),
                 "{{NAME}}": top["name"], "{{OVERALL}}": sp["overall"],
                 "{{LOVE}}": sp["love"], "{{WORK}}": sp["work"],
                 "{{MONEY}}": sp["money"], "{{ADVICE}}": sp["advice"],
                 "{{COLOR}}": sp["color"], "{{ITEM}}": sp["item"]}.items():
        html = html.replace(k, v)
    out_html = HTML_DIR / f'fortune_{day.isoformat()}_spot.html'
    out_html.write_text(html, encoding="utf-8")

    rec = {
        "id": f'fortune_{day.isoformat()}_spot', "genre": "今日の主役star",
        "format": "運勢スポットライトHTML", "kind": "fortune",
        "html": f'html/fortune_{day.isoformat()}_spot.html',
        "hook": f'{date_str} 今日の主役は{top["name"]}！恋愛・仕事・金運まで',
        "caption": f'{top["name"]}の今日の総合運・恋愛運・仕事運・金運・ラッキーをまとめてチェック！',
        "hashtags": ["#今日の運勢", "#星座占い", f'#{top["name"]}', "#shorts"],
        "ft": {
            "instruction": "今日の主役星座のスポットライト運勢のショート台本を作って",
            "input": f'{date_str} 主役={top["name"]} 総合={sp["overall"]}',
            "output": (f'【フック】今日の主役は{top["name"]}！\n'
                       f'【総合運】{sp["overall"]}\n【恋愛運】{sp["love"]}\n'
                       f'【仕事運】{sp["work"]}\n【金運】{sp["money"]}\n'
                       f'【ラッキー】カラーは{sp["color"]}、アイテムは{sp["item"]}\n'
                       f'【締め】{sp["advice"]}')
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
    cards = build(day)  # [(html_name, rec), ...] ランキング＋スポットライト
    for html_name, rec in cards:
        print(f"fortune HTML -> {HTML_DIR / html_name}")

    # JSONL 追記（同idは置換）
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
        png = html_name[:-5] + ".png"  # fortune_<date>(_spot).html → .png
        ok = render_png(html_name, png)
        print(("  PNG OK " if ok else "  PNG NG ") + png)


if __name__ == "__main__":
    main()

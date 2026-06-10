#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily MTG Quiz — Mystery Pair Edition

• Picks one random draftable set (any era) and two random cards from it.
• You guess which set the cards are from, and which of the two is the
  stronger limited pick.
• Ratings: 17Lands avg_pick for modern (Arena-era) sets, Forge's .rnk
  draft rankings for everything older (format #Rank|Name|Rarity|Set,
  rank 1 = best card in the set — the same data Forge's draft AI uses).

Dependencies:
sudo apt install python3-pip msmtp
pip install requests pandas python-dateutil

Cron example (09:00 daily):
0 9 * * * /usr/bin/env python3 /home/pi/daily_draft_quiz.py >> /home/pi/quiz.log 2>&1
"""

import os, random, requests, io, pandas as pd, datetime as dt, json
from urllib.parse import quote
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import ssl

from dotenv import load_dotenv
load_dotenv()

EMAIL_TO   = os.getenv("RECIPIENT_EMAIL")
EMAIL_FROM = os.getenv("GMAIL_SENDER_EMAIL")
USER_AGENT = "PiDraftQuiz/3.0"
HEADERS    = {"User-Agent": USER_AGENT, "Accept": "application/json"}

TODAY       = dt.date.today().isoformat()
SCRY_SETS   = "https://api.scryfall.com/sets"
SCRY_NAMED  = "https://api.scryfall.com/cards/named?fuzzy={name}&set={code}"
LANDS_STATS = "https://www.17lands.com/card_ratings/data?expansion={code}&format=PremierDraft&start_date=2016-01-01"
FORGE_RNK   = "https://raw.githubusercontent.com/Card-Forge/forge/master/forge-gui/res/draft/rankings/{code}.rnk"

# 17Lands only has data for Arena-era sets; XLN (2017-09) is the oldest.
LANDS_CUTOFF = "2017-09-01"

# Minimum rank distance between the two cards, as a fraction of the set
# size, so the "which is stronger" answer isn't a coin flip.
MIN_RANK_GAP = 0.10

MAX_SET_TRIES  = 10   # sets to try before giving up
MAX_CARD_TRIES = 12   # card draws per set before moving to the next set

MAGIC_CARD_BACK = "https://upload.wikimedia.org/wikipedia/en/a/aa/Magic_the_gathering-card_back.jpg"

BASIC_LANDS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}

# Scryfall set code -> Forge .rnk filename, where they disagree
# ("con" is a reserved filename on Windows, hence Forge's "cfx").
FORGE_CODE_ALIASES = {"con": "cfx", "nem": "nms"}


# ---------------------------------------------------------------- ratings

def fetch_17lands(code):
    """Return [(name, rank, total)] from 17Lands avg_pick, or None."""
    code = code.upper()
    folder = "17lands"
    filename = os.path.join(folder, f"{code}.json")
    os.makedirs(folder, exist_ok=True)

    df = None
    try:
        r = requests.get(LANDS_STATS.format(code=code), headers=HEADERS, timeout=30)
        if r.status_code == 200:
            df = pd.read_json(io.StringIO(r.text))
            if not df.empty:
                with open(filename, 'w') as f:
                    json.dump(json.loads(df.to_json(orient='records')), f, indent=2)
        else:
            print(f"17Lands {code}: HTTP {r.status_code}")
    except Exception as e:
        print(f"17Lands {code}: {e}")

    if (df is None or df.empty) and os.path.exists(filename):
        print(f"17Lands {code}: using local cache")
        try:
            df = pd.read_json(filename)
        except Exception as e:
            print(f"17Lands {code}: bad cache file: {e}")
            return None

    if df is None or df.empty or "name" not in df.columns or "avg_pick" not in df.columns:
        return None

    df = df[~df["name"].isin(BASIC_LANDS)].dropna(subset=["avg_pick"])
    df = df.sort_values("avg_pick")  # lower avg_pick = picked earlier = better
    total = len(df)
    if total < 5:
        print(f"17Lands {code}: only {total} rated cards, skipping")
        return None
    return [(str(name), i + 1, total) for i, name in enumerate(df["name"])]


def fetch_forge(code):
    """Return [(name, rank, total)] from Forge's .rnk file, or None."""
    code = FORGE_CODE_ALIASES.get(code.lower(), code.lower())
    folder = "forge"
    filename = os.path.join(folder, f"{code}.rnk")
    os.makedirs(folder, exist_ok=True)

    text = None
    try:
        r = requests.get(FORGE_RNK.format(code=code), headers={"User-Agent": USER_AGENT}, timeout=30)
        if r.status_code == 200:
            text = r.text
            with open(filename, "w") as f:
                f.write(text)
        elif r.status_code != 404:
            print(f"Forge {code}: HTTP {r.status_code}")
    except Exception as e:
        print(f"Forge {code}: {e}")

    if text is None and os.path.exists(filename):
        print(f"Forge {code}: using local cache")
        with open(filename) as f:
            text = f.read()

    if text is None:
        return None

    # Format: #Rank|Name|Rarity|Set  (rank 1 = best card in the set)
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("#"):
            continue
        parts = line[1:].split("|")
        if len(parts) < 4:
            continue
        try:
            entries.append((parts[1].strip(), int(parts[0].strip())))
        except ValueError:
            continue
    if len(entries) < 5:
        print(f"Forge {code}: only {len(entries)} rated cards, skipping")
        return None
    total = max(rank for _, rank in entries)
    return [(name, rank, total) for name, rank in entries]


def get_ratings(set_info):
    """Pick the rating source for a set: 17Lands for modern, Forge otherwise."""
    if set_info["released_at"] >= LANDS_CUTOFF:
        ratings = fetch_17lands(set_info["code"])
        if ratings:
            return ratings, "17Lands"
    ratings = fetch_forge(set_info["code"])
    if ratings:
        return ratings, "Forge"
    print(f"No limited ratings for {set_info['code'].upper()} ({set_info['name']})")
    return None, None


# ---------------------------------------------------------------- cards

def resolve_card(name, set_code):
    """Look the card up on Scryfall (fuzzy: tolerates Forge's stripped accents
    and split-card names). Returns (canonical_name, image_url) or None."""
    url = SCRY_NAMED.format(name=quote(name), code=set_code.lower())
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"Scryfall: no match for '{name}' in {set_code}: HTTP {r.status_code}")
            return None
        card = r.json()
    except Exception as e:
        print(f"Scryfall: error resolving '{name}' in {set_code}: {e}")
        return None

    image = card.get("image_uris", {}).get("normal")
    if not image and card.get("card_faces"):
        image = card["card_faces"][0].get("image_uris", {}).get("normal")
    if not image:
        print(f"Scryfall: no image for '{name}' in {set_code}")
        return None
    return card["name"], image


def get_draftable_sets():
    try:
        r = requests.get(SCRY_SETS, headers=HEADERS, timeout=30)
        r.raise_for_status()
        sets = r.json()["data"]
    except Exception as e:
        raise RuntimeError(f"Could not fetch set list from Scryfall: {e}")
    pool = [s for s in sets
            if s["set_type"] in ("core", "expansion")
            and s.get("released_at", "9999") <= TODAY
            and not s.get("digital", False)]
    if not pool:
        raise RuntimeError("Scryfall returned no draftable sets.")
    return pool


def pick_quiz_pair():
    """Pick a random rated set and two cards from it (with a rank gap)."""
    pool = get_draftable_sets()
    random.shuffle(pool)

    for s in pool[:MAX_SET_TRIES]:
        ratings, source = get_ratings(s)
        if not ratings:
            continue

        total = ratings[0][2]
        min_gap = max(1, int(total * MIN_RANK_GAP))
        picks = []
        for _ in range(MAX_CARD_TRIES):
            name, rank, _ = random.choice(ratings)
            if any(p["rank"] == rank or p["raw_name"] == name for p in picks):
                continue
            if picks and abs(picks[0]["rank"] - rank) < min_gap:
                continue
            resolved = resolve_card(name, s["code"])
            if not resolved:
                continue
            canonical, image = resolved
            picks.append({
                "raw_name": name,
                "name": canonical,
                "image": image,
                "rank": rank,
                "total": total,
            })
            if len(picks) == 2:
                return {
                    "set_code": s["code"].upper(),
                    "set_name": s["name"],
                    "source": source,
                    "cards": picks,
                }
        print(f"Could not assemble a pair from {s['code'].upper()}, trying next set")

    raise RuntimeError(f"No usable set found after {MAX_SET_TRIES} attempts.")


# ---------------------------------------------------------------- email

def send_quiz():
    quiz = pick_quiz_pair()
    cards = quiz["cards"]
    winner = min(cards, key=lambda c: c["rank"])

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"MTG Daily Quiz — Mystery Pair ({TODAY})"
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    labels = ["A", "B"]
    winner_label = labels[cards.index(winner)]

    plain_text = "Guess which set these cards are from, and which is the stronger limited pick:\n"
    plain_text += "\n".join(f"- Card {l}: {c['name']}" for l, c in zip(labels, cards))
    plain_text += (
        f"\n\nAnswers:\nSet: {quiz['set_name']} ({quiz['set_code']})\n"
        + "\n".join(f"Card {l}: #{c['rank']} of {c['total']}" for l, c in zip(labels, cards))
        + f"\nStronger pick: Card {winner_label} — {winner['name']}"
    )

    html_cards = "".join(
        f'<div><h3>Card {l}</h3><img src="{c["image"]}" height="350"></div><br>'
        for l, c in zip(labels, cards)
    )

    html_answers = "".join(
        f"<tr><td>Card {l}</td><td>{c['name']}</td>"
        f"<td>#{c['rank']} of {c['total']} (top {100 * c['rank'] / c['total']:.0f}%)</td></tr>"
        for l, c in zip(labels, cards)
    )

    html_content = f"""
    <html>
      <body>
        <h2>Today's Quiz: which set — and which is the stronger limited pick?</h2>
        {html_cards}
        <div style="margin:30px 0;"><img src="{MAGIC_CARD_BACK}" height="350"></div>
        <h3>Answers</h3>
        <p>Set: <b>{quiz['set_name']} ({quiz['set_code']})</b> — ratings from {quiz['source']}</p>
        <table border="1" cellpadding="10">
          <tr><th></th><th>Card</th><th>Limited rating</th></tr>
          {html_answers}
        </table>
        <p><b>Stronger limited pick: Card {winner_label} — {winner['name']}</b></p>
      </body>
    </html>
    """

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    # -------------------- send via SMTP --------------------
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))         # 465 = SSL; use 587 for STARTTLS
    smtp_user = os.getenv("SMTP_USER", EMAIL_FROM)
    smtp_pass = os.getenv("SMTP_PASS")

    if not smtp_pass:
        raise RuntimeError("SMTP_PASS environment variable not set.")

    context = ssl.create_default_context()

    with smtplib.SMTP_SSL(host=smtp_host, port=smtp_port, context=context) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())

    print(f"{TODAY}: sent quiz for {quiz['set_name']} ({quiz['set_code']}), "
          f"cards: {', '.join(c['name'] for c in cards)}")

if __name__ == '__main__':
    send_quiz()

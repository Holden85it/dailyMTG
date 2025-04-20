#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily MTG Draft P1P1 Quiz — Enhanced HTML Version

• Automatically selects the latest draftable set with 17Lands data.
• Picks 5 random non-basic land cards for a quiz.
• Sends a multipart email (plain text + HTML) showing cards, a buffer image, and reveals ranked answers at the end.

Dependencies:
sudo apt install python3-pip msmtp
pip install requests pandas python-dateutil

Cron example (09:00 daily):
0 9 * * * /usr/bin/env python3 /home/pi/daily_draft_quiz.py >> /home/pi/quiz.log 2>&1
"""

import os, random, subprocess, requests, pandas as pd, datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

EMAIL_TO   = os.getenv("EMAIL_TO",   "lcmasiero@gmail.com")
EMAIL_FROM = os.getenv("EMAIL_FROM", "lcmasiero@gmail.com")
USER_AGENT = "PiDraftQuiz/2.0"
HEADERS    = {"User-Agent": USER_AGENT, "Accept": "application/json"}

TODAY       = dt.date.today().isoformat()
SCRY_SETS   = "https://api.scryfall.com/sets"
SCRY_CARDS  = "https://api.scryfall.com/cards/search?q=set:{code}+unique:cards"
LANDS_STATS = "https://www.17lands.com/card_ratings/data?expansion={code}&format=PremierDraft"

MAGIC_CARD_BACK = "https://upload.wikimedia.org/wikipedia/en/a/aa/Magic_the_gathering-card_back.jpg"

# Fetch cards from Scryfall, excluding basic lands
def fetch_cards(code):
    url = SCRY_CARDS.format(code=code)
    cards = []
    while url:
        r = requests.get(url, headers=HEADERS).json()
        cards += [c["name"] for c in r.get("data", []) if 'Basic Land' not in c["type_line"]]
        url = r.get("next_page")
    return cards

# Fetch stats from 17Lands
def fetch_17lands(code):
    url = LANDS_STATS.format(code=code.upper())
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return None
    return pd.read_json(r.text)

# Select latest valid set
def select_latest_valid_set():
    sets = requests.get(SCRY_SETS, headers=HEADERS).json()["data"]
    draftable = sorted([s for s in sets if s["set_type"] in ("core", "expansion") and s.get("released_at") <= TODAY], key=lambda s: s["released_at"], reverse=True)
    for s in draftable:
        code = s["code"]
        cards = fetch_cards(code)
        lands = fetch_17lands(code)
        if lands is not None and not lands.empty and len(cards) >= 5:
            return code, s["name"], cards, lands
    raise RuntimeError("No valid set found.")

# Build and send quiz email
def send_quiz():
    set_code, set_name, cards, lands_df = select_latest_valid_set()
    quiz_cards = random.sample(cards, 3)

    rates = {}
    for card in quiz_cards:
        match = lands_df[lands_df["name"].str.strip() == card]
        rates[card] = float(match["avg_pick"].values[0]) if not match.empty else 0.0

    ranked_cards = sorted(quiz_cards, key=lambda c: rates[c], reverse=True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"MTG Daily Quiz — {set_name} ({set_code.upper()})"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    plain_text = "\n".join([f"- {c}" for c in quiz_cards])

    html_content = f"""
    <html>
    <body>
    <h2>Today's Draft Quiz: {set_name}</h2>
    {''.join([f'<div><img src="https://api.scryfall.com/cards/named?exact={c}&format=image" height="350"></div><br>' for c in quiz_cards])}

    <div style="margin:30px 0;"><img src="{MAGIC_CARD_BACK}" height="350"></div>

    <h3>Ranked Answers (Best picks at the bottom)</h3>
    <table border="1" cellpadding="10">
        <tr><th>Rank</th><th>Card</th><th>Average Pick</th></tr>
        {''.join([f'<tr><td>{5-i}</td><td>{c}</td><td>{rates[c]:.2f}</td></tr>' for i, c in enumerate(ranked_cards)])}
    </table>
    </body>
    </html>
    """

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    subprocess.run(["msmtp", "-t"], input=msg.as_bytes(), check=True)

if __name__ == '__main__':
    send_quiz()

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

import os, random, subprocess, requests, pandas as pd, datetime as dt, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
load_dotenv()

CARD_NUMBER = 3

EMAIL_TO   = os.getenv("RECIPIENT_EMAIL")
EMAIL_FROM = os.getenv("GMAIL_SENDER_EMAIL")
USER_AGENT = "PiDraftQuiz/2.0"
HEADERS    = {"User-Agent": USER_AGENT, "Accept": "application/json"}

TODAY       = dt.date.today().isoformat()
SCRY_SETS   = "https://api.scryfall.com/sets"
SCRY_CARDS  = "https://api.scryfall.com/cards/search?q=set:{code}+unique:cards"
LANDS_STATS = "https://www.17lands.com/card_ratings/data?expansion={code}&format=PremierDraft&start_date=2016-01-01"

MAGIC_CARD_BACK = "https://upload.wikimedia.org/wikipedia/en/a/aa/Magic_the_gathering-card_back.jpg"

WEEKEND_SETS = {
    "XLN": "Ixalan",
    "RIX": "Rivals of Ixalan",
    "DOM": "Dominaria",
    "M19": "Core Set 2019",
    "GRN": "Guilds of Ravnica",
    "RNA": "Ravnica Allegiance",
    "WAR": "War of the Spark",
    "M20": "Core Set 2020",
    "ELD": "Throne of Eldraine",
    "THB": "Theros Beyond Death",
    "IKO": "Ikoria: Lair of Behemoths",
    "M21": "Core Set 2021",
    "ZNR": "Zendikar Rising",
    "KHM": "Kaldheim",
    "STX": "Strixhaven: School of Mages",
    "AFR": "Adventures in the Forgotten Realms",
    "MID": "Innistrad: Midnight Hunt",
    "VOW": "Innistrad: Crimson Vow",
    "NEO": "Kamigawa: Neon Dynasty",
    "SNC": "Streets of New Capenna",
    "DMU": "Dominaria United",
    "BRO": "The Brothers' War",
    "ONE": "Phyrexia: All Will Be One",
    "MOM": "March of the Machine",
    "WOE": "Wilds of Eldraine"
}

# Fetch cards from Scryfall, excluding basic lands
def fetch_cards(code):
    code = code.lower()
    folder = "scryfall"
    filename = os.path.join(folder, f"{code}_cards.json")
    
    os.makedirs(folder, exist_ok=True)
    url = SCRY_CARDS.format(code=code)
    cards = []

    try:
        while url:
            r = requests.get(url, headers=HEADERS)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")
            data = r.json()
            cards += [c["name"] for c in data.get("data", []) if 'Basic Land' not in c["type_line"]]
            url = data.get("next_page")
        with open(filename, "w") as f:
            json.dump(cards, f, indent=2)
        return cards
    except Exception as e:
        print(f"Error fetching cards: {e}")

    # Try to load from local file if fetch failed
    if os.path.exists(filename):
        print(f"Loading cards from local cache: {filename}")
        with open(filename, "r") as f:
            return json.load(f)

    print("No card data available.")
    return []

# Fetch stats from 17Lands
def fetch_17lands(code):
    code = code.upper()
    folder = "17lands"
    filename = os.path.join(folder, f"{code}.json")
    
    # Ensure the folder exists
    os.makedirs(folder, exist_ok=True)

    url = LANDS_STATS.format(code=code)
    try:
        r = requests.get(url, headers=HEADERS)
        if r.status_code == 200:
            df = pd.read_json(r.text)

    	    # Save as pretty JSON manually
            with open(filename, 'w') as f:
            	json.dump(json.loads(df.to_json(orient='records')), f, indent=2)
            
            return df
        else:
            print(f"Failed to fetch from web. Status code: {r.status_code}")
    except Exception as e:
        print(f"Error fetching data: {e}")

    # Try to load from local file if fetch failed
    if os.path.exists(filename):
        print(f"Loading data from local cache: {filename}")
        return pd.read_json(filename)

    print("No data available.")
    return None

# Select latest valid set
def select_latest_valid_set():

    today = dt.datetime.today().weekday()  # Monday=0, Sunday=6
    if today >= 4:  # Friday (4), Saturday (5), Sunday (6)
        code = random.choice(list(WEEKEND_SETS.keys()))
        setName = WEEKEND_SETS[code]
    else:
        sets = requests.get(SCRY_SETS, headers=HEADERS).json()["data"]
        draftable = sorted([s for s in sets if s["set_type"] in ("core", "expansion") and s.get("released_at") <= TODAY], key=lambda s: s["released_at"], reverse=True)
        code = draftable[0]["code"]
        setName = draftable[0]["name"]
    cards = fetch_cards(code)
    lands = fetch_17lands(code)
    if lands is not None and not lands.empty and len(cards) >= 5:
        return code, setName, cards, lands
    raise RuntimeError("No valid set found.")

# Build and send quiz email
def send_quiz():
    set_code, set_name, cards, lands_df = select_latest_valid_set()
    quiz_cards = random.sample(cards, CARD_NUMBER)

    rates = {}
    for card in quiz_cards:
        cardFirstName = card.split(" //", 1)[0]
        match = lands_df[lands_df["name"].str.strip() == cardFirstName]
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
        {''.join([f'<tr><td>{CARD_NUMBER-i}</td><td>{c}</td><td>{rates[c]:.2f}</td></tr>' for i, c in enumerate(ranked_cards)])}
    </table>
    </body>
    </html>
    """

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    subprocess.run(["msmtp", "-t"], input=msg.as_bytes(), check=True)

if __name__ == '__main__':
    send_quiz()

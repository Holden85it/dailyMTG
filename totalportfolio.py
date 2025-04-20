#!/usr/bin/env python3
"""
portfolio_tracker.py – Retrieve crypto quotes from CoinMarketCap,
calculate portfolio value & PnL, and push the result (or any error) to Pushbullet.

Exit codes:
    0   – success
  100   – network problem contacting CoinMarketCap
  101   – bad response / unexpected json from CoinMarketCap
  200   – could not read/write CSV files
  300   – portfolio/PnL calculation error
  400   – pushbullet request failed
"""

import csv
import sys
import datetime as dt
from pathlib import Path
from typing import Dict, List

import requests
import pandas as pd
from requests.exceptions import RequestException

# --------------------------------------------------------------------------- #
# Configuration – prefer env vars over literals
CMC_API_KEY = "738beaa5-ec04-4767-8a84-5509e5afb6da"
CMC_ENDPOINT = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"

PUSHBULLET_KEY = "o.52oPsw0YJky0iG8Xwksnk7VR32SDx1yy"
PUSH_ENDPOINT = "https://api.pushbullet.com/v2/pushes"  # keep configurable if needed

CURRENCIES = [
    "BTC", "ETH", "ADA", "DOGE", "ATOM", "DOT",
    "LTC", "XLM", "XRP", "XMR", "BCH", "POL", "SOL"
]
CONVERT_TO = ["GBP"]

DATA_DIR = Path(__file__).resolve().parent
PRICES_CSV = DATA_DIR / "currentprices.csv"
PORTFOLIO_CSV = DATA_DIR / "quantities.csv"
HISTORY_CSV = DATA_DIR / "portfolioHistory.csv"

# --------------------------------------------------------------------------- #
def send_push(title: str, body: str) -> None:
    """Send a note to Pushbullet; raise on failure."""
    payload = {"type": "note", "title": title, "body": body}
    headers = {"Access-Token": PUSHBULLET_KEY, "Content-Type": "application/json"}
    resp = requests.post(PUSH_ENDPOINT, json=payload, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Pushbullet error: {resp.status_code} – {resp.text[:100]}")

# --------------------------------------------------------------------------- #
def fetch_prices() -> pd.DataFrame:
    params = {"symbol": ",".join(CURRENCIES), "convert": ",".join(CONVERT_TO)}
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    try:
        resp = requests.get(CMC_ENDPOINT, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
    except RequestException as exc:
        raise ConnectionError(f"CoinMarketCap connection failed: {exc}") from exc

    try:
        data = resp.json()["data"]
        rows = [
            {"Currency": cur, "Convert To": conv, "Price": data[cur]["quote"][conv]["price"]}
            for cur in CURRENCIES
            for conv in CONVERT_TO
            if cur in data
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Unexpected JSON format from CoinMarketCap") from exc

    df = pd.DataFrame(rows)
    df.to_csv(PRICES_CSV, index=False)
    return df

# --------------------------------------------------------------------------- #
def load_csv_safe(path: Path, expected_headers: List[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    df = pd.read_csv(path)
    missing = set(expected_headers) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing columns: {', '.join(missing)}")
    return df

# --------------------------------------------------------------------------- #
def portfolio_value(prices: pd.DataFrame, qty: pd.DataFrame) -> float:
    merged = qty.merge(prices, how="left", on="Currency")
    if merged["Price"].isna().any():
        missing = merged[merged["Price"].isna()]["Currency"].unique()
        raise ValueError(f"Price missing for: {', '.join(missing)}")
    merged["Value"] = merged["Quantity"] * merged["Price"]
    return merged["Value"].sum()

# --------------------------------------------------------------------------- #
def pnl(history_df: pd.DataFrame, current_val: float) -> Dict[str, float]:
    out: Dict[str, float] = {"today": 0.0, "weekly": 0.0, "monthly": 0.0}
    if history_df.empty:
        return out

    today = dt.datetime.now()
    last_val = float(history_df.iloc[-1]["Value"])
    out["today"] = current_val - last_val

    one_week_ago = today - dt.timedelta(weeks=1)
    weekly = history_df[history_df["Date"] == one_week_ago.strftime("%d-%b-%Y")]
    if not weekly.empty:
        out["weekly"] = current_val - float(weekly.iloc[-1]["Value"])

    last_month_day = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%d-%b-%Y")
    monthly = history_df[history_df["Date"] == last_month_day]
    if not monthly.empty:
        out["monthly"] = current_val - float(monthly.iloc[-1]["Value"])
    return out

# --------------------------------------------------------------------------- #
def append_history(history_path: Path, value: float) -> None:
    today_str = dt.datetime.now().strftime("%d-%b-%Y")
    mode = "a" if history_path.exists() else "w"
    with open(history_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Value"], lineterminator="\n")
        if mode == "w":
            writer.writeheader()
        writer.writerow({"Date": today_str, "Value": int(round(value, 0))})

# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        prices_df = fetch_prices()                            # may raise 100/101
    except ConnectionError as e:
        send_push("DailyPnL – ERROR 100", str(e))
        return 100
    except ValueError as e:
        send_push("DailyPnL – ERROR 101", str(e))
        return 101

    try:
        qty_df = load_csv_safe(PORTFOLIO_CSV, ["Currency", "Quantity"])
    except (FileNotFoundError, ValueError) as e:
        send_push("DailyPnL – ERROR 200", str(e))
        return 200

    try:
        current_val = portfolio_value(prices_df, qty_df)
    except ValueError as e:
        send_push("DailyPnL – ERROR 300", str(e))
        return 300

    # Load history (non‑fatal if missing)
    history_df = pd.read_csv(HISTORY_CSV) if HISTORY_CSV.exists() else pd.DataFrame()

    pnl_info = pnl(history_df, current_val)
    body_lines = [
        f"Portfolio value: £{int(round(current_val, 0)):,}",
        f"Daily PnL: {int(round(pnl_info['today'], 0)):+}",
        f"Weekly PnL: {int(round(pnl_info['weekly'], 0)):+}",
        f"Monthly PnL: {int(round(pnl_info['monthly'], 0)):+}",
    ]
    body_msg = "\n".join(body_lines)

    try:
        send_push("DailyPnL", body_msg)
    except RuntimeError as e:
        # Push failed – nothing more we can do; return error
        print(e, file=sys.stderr)
        return 400

    # Update history *after* successful push so we don't record failed days
    try:
        append_history(HISTORY_CSV, current_val)
    except OSError as e:
        # Can't write history, but the main job succeeded
        print(f"Warning: could not write history – {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

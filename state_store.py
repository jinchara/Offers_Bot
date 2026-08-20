"""
state_store.py
Shared read/write helpers for the bot's persisted state:
  - data/offers.json    (current known offers, keyed by slug)
  - data/history.jsonl  (one line per day: {date, offer_count})

Pulled out into its own module so main.py, reports.py, and
telegram_commands.py all read/write the same way instead of each having
their own copy of this logic.
"""

import json
import os
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STATE_FILE = os.path.join(DATA_DIR, "offers.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_history(offer_count: int):
    os.makedirs(DATA_DIR, exist_ok=True)
    record = {"date": date.today().isoformat(), "offer_count": offer_count}
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
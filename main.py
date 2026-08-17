"""
main.py
Run this once a day (via GitHub Actions). It:
  1. Fetches all current offers from TBC's site.
  2. Compares against data/offers.json (state from the previous run).
  3. Sends a Telegram message for every NEW offer, and a note for
     offers that disappeared (expired/ended).
  4. Appends today's snapshot to data/history.jsonl for weekly/monthly reports.
  5. Overwrites data/offers.json with the current state.

Designed to be safe to re-run: if it fails partway, nothing is corrupted
because we only write files at the very end.
"""

import json
import os
from datetime import date

from scraper import fetch_all_offers
from categorize import categorize
from telegram_notify import send_message, format_new_offer_message

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


def append_history(offers: list[dict]):
    os.makedirs(DATA_DIR, exist_ok=True)
    record = {"date": date.today().isoformat(), "offer_count": len(offers)}
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    print("Fetching current offers from TBC...")
    current_offers = fetch_all_offers()
    print(f"Found {len(current_offers)} offers.")

    previous_state = load_state()
    previous_slugs = set(previous_state.keys())
    current_slugs = {o["slug"] for o in current_offers}

    new_slugs = current_slugs - previous_slugs
    expired_slugs = previous_slugs - current_slugs

    new_offers = [o for o in current_offers if o["slug"] in new_slugs]

    if not previous_state:
        print("No previous state found — first run, skipping notifications "
              "for the initial batch to avoid spamming you with everything at once.")
    else:
        for offer in new_offers:
            category = categorize(offer)
            try:
                send_message(format_new_offer_message(offer, category))
            except Exception as e:
                print(f"Failed to send Telegram message for {offer['slug']}: {e}")

        if expired_slugs:
            names = [previous_state[s].get("title", s) for s in expired_slugs]
            try:
                send_message(
                    "⌛️ დასრულებული შეთავაზებები:\n" + "\n".join(f"• {n}" for n in names)
                )
            except Exception as e:
                print(f"Failed to send expiry notice: {e}")

    # Build new state, preserving first_seen dates
    new_state = {}
    for offer in current_offers:
        prior = previous_state.get(offer["slug"], {})
        new_state[offer["slug"]] = {
            **offer,
            "category": categorize(offer),
            "first_seen": prior.get("first_seen", date.today().isoformat()),
            "last_seen": date.today().isoformat(),
        }

    save_state(new_state)
    append_history(current_offers)
    print(f"Done. {len(new_slugs)} new, {len(expired_slugs)} expired.")


if __name__ == "__main__":
    main()

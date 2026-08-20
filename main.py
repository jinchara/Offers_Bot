"""
main.py
Run this once a day (via GitHub Actions). It:
  1. Fetches all current offers from TBC's site.
  2. Compares against data/offers.json (state from the previous run).
  3. Sends a Telegram message for every NEW offer, and a note for
     offers that disappeared (expired/ended).
  4. Detects cashback % changes on offers that already existed
     (e.g. a merchant bumping their rate from 15% to 25%).
  5. Sends an "ending soon" digest for offers expiring within a couple days.
  6. Appends today's snapshot to data/history.jsonl for weekly/monthly reports.
  7. Overwrites data/offers.json with the current state.

Designed to be safe to re-run: if it fails partway, nothing is corrupted
because we only write files at the very end.
"""

from datetime import date

from scraper import fetch_all_offers
from categorize import categorize, extract_offer_economics
from telegram_notify import (
    send_message,
    format_new_offer_message,
    format_price_change_message,
    format_ending_soon_message,
)
from state_store import load_state, save_state, append_history

# Offers with this many days or fewer left get included in the
# "ending soon" digest.
ENDING_SOON_THRESHOLD = 2

# Keep at most this many cashback-history entries per offer, so
# data/offers.json doesn't grow unbounded over months of runs.
MAX_CASHBACK_HISTORY = 20


def main():
    print("Fetching current offers from TBC...")
    current_offers = fetch_all_offers()
    print(f"Found {len(current_offers)} offers.")

    previous_state = load_state()
    previous_slugs = set(previous_state.keys())
    current_slugs = {o["slug"] for o in current_offers}

    new_slugs = current_slugs - previous_slugs
    expired_slugs = previous_slugs - current_slugs
    existing_slugs = current_slugs & previous_slugs

    new_offers = [o for o in current_offers if o["slug"] in new_slugs]

    if not previous_state:
        print("No previous state found — first run, skipping notifications "
              "for the initial batch to avoid spamming you with everything at once.")
    else:
        # --- brand-new offers ---
        for offer in new_offers:
            category = categorize(offer)
            economics = extract_offer_economics(offer)
            try:
                send_message(format_new_offer_message(offer, category, economics))
            except Exception as e:
                print(f"Failed to send Telegram message for {offer['slug']}: {e}")

        # --- expired offers ---
        if expired_slugs:
            names = [previous_state[s].get("title", s) for s in expired_slugs]
            try:
                send_message(
                    "⌛️ დასრულებული შეთავაზებები:\n" + "\n".join(f"• {n}" for n in names)
                )
            except Exception as e:
                print(f"Failed to send expiry notice: {e}")

        # --- cashback % changes on offers that already existed ---
        for offer in current_offers:
            if offer["slug"] not in existing_slugs:
                continue
            prior = previous_state[offer["slug"]]
            new_economics = extract_offer_economics(offer)
            old_percent = prior.get("cashback_percent")
            new_percent = new_economics.get("cashback_percent")
            if (
                old_percent is not None
                and new_percent is not None
                and old_percent != new_percent
            ):
                try:
                    send_message(format_price_change_message(offer, old_percent, new_percent))
                except Exception as e:
                    print(f"Failed to send price-change message for {offer['slug']}: {e}")

        # --- ending-soon digest ---
        ending_soon = [
            o for o in current_offers
            if o.get("remaining_days") is not None
            and o["remaining_days"] <= ENDING_SOON_THRESHOLD
        ]
        if ending_soon:
            try:
                send_message(format_ending_soon_message(ending_soon))
            except Exception as e:
                print(f"Failed to send ending-soon digest: {e}")

    # Build new state, preserving first_seen dates and cashback history
    new_state = {}
    for offer in current_offers:
        prior = previous_state.get(offer["slug"], {})
        economics = extract_offer_economics(offer)

        cashback_history = prior.get("cashback_history", [])
        latest_recorded = cashback_history[-1]["percent"] if cashback_history else None
        if latest_recorded != economics.get("cashback_percent"):
            cashback_history = cashback_history + [{
                "date": date.today().isoformat(),
                "percent": economics.get("cashback_percent"),
            }]
        cashback_history = cashback_history[-MAX_CASHBACK_HISTORY:]

        new_state[offer["slug"]] = {
            **offer,
            "category": categorize(offer),
            **economics,
            "cashback_history": cashback_history,
            "first_seen": prior.get("first_seen", date.today().isoformat()),
            "last_seen": date.today().isoformat(),
        }

    save_state(new_state)
    append_history(len(current_offers))
    print(
        f"Done. {len(new_slugs)} new, {len(expired_slugs)} expired, "
        f"{len(existing_slugs)} existing offers checked for changes."
    )


if __name__ == "__main__":
    main()
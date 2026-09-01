"""
main.py
The daily job. Run by .github/workflows/check_offers.yml.

  1. Fetch every offer from TBC's API.
  2. Optionally read TBC's own category tags (see scraper.fetch_category_map).
  3. Enrich each offer: category, channel, economics, live status.
  4. Diff against the previous run and notify on what actually changed.
  5. Merge into state WITHOUT deleting anything — offers TBC drops are
     archived, not forgotten.
  6. Rebuild data/insights.json and append a status-aware history row.

Safe to re-run: all writes happen at the end and are atomic.

CHANGES THAT MATTER
-------------------
* "Expired" used to mean "disappeared from the API". It now means "its end
  date has passed", which is what the word actually means and what the
  dashboard needs. Disappearing from the listing is tracked separately as
  delisting.
* The ending-soon digest no longer includes offers that already ended —
  the bug where finished campaigns sat under "მალე იწურება" with 0 days.
* Offers that haven't started yet are announced as upcoming rather than
  silently counted as live.
"""

import os
from datetime import date

import requests

from analytics import build_insights, print_report
from categorize import classify, extract_offer_economics
from offer_status import ENDING_SOON_DAYS, compute_status
from scraper import (
    fetch_all_offers,
    fetch_facet_tags,
    fetch_segment_membership,
    resolve_facet_values,
)
from state_store import (
    append_history,
    load_state,
    prune_archive,
    save_insights,
    save_state,
)
from telegram_notify import (
    format_ending_soon_message,
    format_new_offer_message,
    format_price_change_message,
    format_upcoming_message,
    send_message,
)

# Keep at most this many cashback-history entries per offer so offers.json
# doesn't grow without bound over months of runs.
MAX_CASHBACK_HISTORY = 20

# TBC's own filter facets give exact categories instead of inferred ones.
# Costs ~35 extra paginated requests a day. Set USE_TBC_CATEGORIES=0 to
# skip it and fall back to categorize.py's keyword layer.
USE_TBC_CATEGORIES = os.environ.get("USE_TBC_CATEGORIES", "1") != "0"

# Notifications are skipped entirely when Telegram isn't configured, so the
# scraper is still usable as a pure data pipeline.
TELEGRAM_READY = bool(
    os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")
)


def notify(text: str, context: str) -> None:
    """Sends a message, but never lets a Telegram outage fail the data run."""
    if not TELEGRAM_READY:
        return
    try:
        send_message(text)
    except Exception as e:
        print(f"Telegram send failed ({context}): {e}")


def enrich(offer: dict, facet_tags: dict, segments: list, prior: dict,
           today: date) -> dict:
    """Builds the full stored record for one offer."""
    facet_tags = facet_tags or {}
    api_categories = facet_tags.get("Category") or None
    classification = classify(offer, api_categories)
    economics = extract_offer_economics(offer)
    status = compute_status(offer, today)

    history = list(prior.get("cashback_history") or [])
    latest = history[-1]["percent"] if history else None
    if latest != economics["cashback_percent"]:
        history.append({
            "date": today.isoformat(),
            "percent": economics["cashback_percent"],
        })
    history = history[-MAX_CASHBACK_HISTORY:]

    # TBC's own tags, when we have them, are authoritative and are stored
    # separately from our inferred fields so the two never get confused.
    return {
        **offer,
        **classification,
        **economics,
        **status,
        "tbc_categories": facet_tags.get("Category") or [],
        "product_types": facet_tags.get("ProductType") or [],
        "tbc_offer_types": facet_tags.get("OfferType") or [],
        "card_types": facet_tags.get("CardType") or [],
        "segments": segments or [],
        "concept_only": segments == ["Concept"],
        "cashback_history": history,
        "first_seen": prior.get("first_seen", today.isoformat()),
        "last_seen": today.isoformat(),
        "still_listed": True,
        "delisted_on": None,
    }


def main():
    today = date.today()

    print("Fetching offers from TBC...")
    try:
        current = fetch_all_offers()
    except requests.RequestException as e:
        # Nothing has been written yet, so the previous good offers.json is
        # untouched. Exit non-zero so the Actions run is visibly red rather
        # than quietly committing nothing.
        print(f"ERROR: could not reach TBC's API: {e}")
        print("Existing data left unchanged. This is usually a transient "
              "outage or a block on the runner's IP — check by running "
              "`python scraper.py` locally.")
        raise SystemExit(1)

    if not current:
        print("ERROR: the API returned zero offers. Refusing to overwrite "
              "existing data with an empty set — this is almost always an "
              "API shape change, not TBC ending every campaign at once.")
        raise SystemExit(1)

    print(f"  {len(current)} offers returned.")

    facet_tags, segment_membership = {}, {}
    if USE_TBC_CATEGORIES:
        print("\nReading TBC's own filter tags...")
        try:
            resolved = resolve_facet_values(verbose=False)
            facet_tags = fetch_facet_tags(resolved)
            segment_membership = fetch_segment_membership()
        except Exception as e:
            # Never fatal. Losing exact tags costs accuracy, not the run.
            print(f"  Facet tagging failed, falling back to keywords: {e}")

    if facet_tags:
        tagged = sum(1 for t in facet_tags.values() if t.get("Category"))
        print(f"  Exact categories for {tagged}/{len(current)} offers "
              f"({100 * tagged // max(len(current), 1)}%).")
    else:
        print("  No facet tags — categories will be inferred from text.")

    previous = load_state()
    first_run = not previous

    current_by_slug = {o["slug"]: o for o in current if o.get("slug")}
    new_slugs = set(current_by_slug) - set(previous)
    delisted_slugs = set(previous) - set(current_by_slug)

    # --- build the new state ---------------------------------------------
    state = {}

    for slug, offer in current_by_slug.items():
        state[slug] = enrich(
            offer,
            facet_tags.get(slug),
            segment_membership.get(slug, ["All"] if not segment_membership else []),
            previous.get(slug, {}),
            today,
        )

    # Offers TBC removed from the listing: keep them, mark them, and refresh
    # their status so an archived record still reports "ended" correctly.
    for slug in delisted_slugs:
        archived = dict(previous[slug])
        archived.update(compute_status(archived, today))
        if archived.get("still_listed", True):
            archived["delisted_on"] = today.isoformat()
        archived["still_listed"] = False
        state[slug] = archived

    state = prune_archive(state, today)

    # --- work out what to shout about -------------------------------------
    live = [o for o in state.values() if o["is_live"]]
    newly_added = [state[s] for s in new_slugs if s in state]

    just_ended = [
        state[s] for s in previous
        if s in state
        and state[s]["status"] == "ended"
        and previous[s].get("status") not in (None, "ended")
    ]

    just_started = [
        state[s] for s in state
        if previous.get(s, {}).get("status") == "upcoming"
        and state[s]["status"] in ("active", "ending_soon")
    ]

    ending_soon = sorted(
        (o for o in live
         if o["days_left"] is not None and 0 <= o["days_left"] <= ENDING_SOON_DAYS),
        key=lambda o: o["days_left"],
    )

    rate_changes = []
    for slug, offer in state.items():
        prior = previous.get(slug)
        if not prior:
            continue
        old, new = prior.get("cashback_percent"), offer.get("cashback_percent")
        if old is not None and new is not None and old != new:
            rate_changes.append((offer, old, new))

    # --- notify ------------------------------------------------------------
    if first_run:
        print("First run — skipping notifications so you don't get "
              f"{len(current)} messages at once.")
    elif not TELEGRAM_READY:
        print("Telegram not configured — data written, notifications skipped.")
    else:
        # A newly *discovered* offer is not necessarily a newly *live* one.
        # TBC's listing includes finished and not-yet-started campaigns, so
        # announcing an already-ended offer as "🆕 ახალი შეთავაზება" would
        # be wrong. Split them by status.
        for offer in newly_added:
            if offer["status"] == "ended":
                continue          # discovered late; it belongs in the archive
            if offer["status"] == "upcoming":
                continue          # covered by the digest below
            notify(
                format_new_offer_message(offer, offer["category"], offer),
                offer["slug"],
            )

        newly_upcoming = [o for o in newly_added if o["status"] == "upcoming"]
        if newly_upcoming:
            notify(format_upcoming_message(newly_upcoming), "upcoming")

        if just_started:
            notify(
                "▶️ <b>დაიწყო:</b>\n"
                + "\n".join(f"• {o.get('title')}" for o in just_started[:30]),
                "started",
            )

        if just_ended:
            notify(
                "⌛️ <b>დასრულებული შეთავაზებები:</b>\n"
                + "\n".join(f"• {o.get('title')}" for o in just_ended[:30]),
                "ended",
            )

        for offer, old, new in rate_changes:
            notify(format_price_change_message(offer, old, new), offer["slug"])

        if ending_soon:
            notify(format_ending_soon_message(ending_soon), "ending-soon")

    # --- persist -----------------------------------------------------------
    save_state(state)

    status_counts = {}
    for offer in state.values():
        status_counts[offer["status"]] = status_counts.get(offer["status"], 0) + 1

    append_history({
        "total_known": len(state),
        "live": len(live),
        "upcoming": status_counts.get("upcoming", 0),
        "ended": status_counts.get("ended", 0),
        "evergreen": status_counts.get("evergreen", 0),
        "new_today": len(newly_added),
        "delisted_today": len(delisted_slugs),
        # Kept so older history rows and the trend chart stay comparable.
        "offer_count": len(live),
    })

    insights = build_insights(state, today)
    save_insights(insights)
    print_report(insights)

    print(f"\nDone. {len(newly_added)} new, {len(just_ended)} newly ended, "
          f"{len(delisted_slugs)} delisted, {len(rate_changes)} rate changes.")


if __name__ == "__main__":
    main()

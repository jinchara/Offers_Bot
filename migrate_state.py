"""
migrate_state.py
One-off upgrade of an existing data/offers.json to the new schema.

Run this once after pulling these changes, so the dashboard is correct
immediately instead of waiting for the next scheduled scrape:

    python migrate_state.py

WHAT IT CAN AND CANNOT RECOVER
------------------------------
The old records stored `remaining_days` clamped with `max(days, 0)`, so:

  * remaining_days > 0  -> end date is recoverable exactly:
                           last_seen + remaining_days.
  * remaining_days == 0 -> the true end date is unrecoverable. It could be
                           tonight, or three months ago; the clamp erased
                           the difference. These are marked
                           date_source = "migrated_uncertain" and given an
                           end date of last_seen, which is the earliest
                           date consistent with the data.
  * remaining_days None -> no end date was ever published. Treated as an
                           open-ended offer.

The next scrape overwrites all of this with real API dates, so the
uncertainty lasts one run. Everything else — categories, channel,
economics, status — is fully recomputed from scratch.
"""

from datetime import date, timedelta

from analytics import build_insights, print_report
from categorize import classify, extract_offer_economics
from ka_dates import extract_date_range, infer_end_date
from offer_status import compute_status
from state_store import load_state, save_insights, save_state


def migrate():
    state = load_state()
    if not state:
        print("No data/offers.json found — nothing to migrate.")
        return

    today = date.today()
    exact = uncertain = openended = recovered_from_copy = starts_recovered = 0

    migrated = {}
    for slug, offer in state.items():
        record = dict(offer)

        if not record.get("end_date"):
            days = record.get("remaining_days")
            last_seen = record.get("last_seen")
            if days is None:
                record["end_date"] = None
                record["date_source"] = "no_end_date"
                openended += 1
            elif days > 0 and last_seen:
                end = date.fromisoformat(last_seen) + timedelta(days=days)
                record["end_date"] = f"{end.isoformat()}T23:59:00"
                record["date_source"] = "migrated_exact"
                exact += 1
            elif last_seen:
                # days == 0 under the old clamp: could be "ends tonight" or
                # "ended months ago". The offer copy usually says which, and
                # we know the answer can't be later than today.
                inferred = infer_end_date(
                    record,
                    reference=date.fromisoformat(record.get("first_seen") or last_seen),
                    max_date=today,
                )
                if inferred:
                    record["end_date"] = f"{inferred.isoformat()}T23:59:00"
                    record["date_source"] = "parsed_from_copy"
                    recovered_from_copy += 1
                else:
                    record["end_date"] = f"{last_seen}T23:59:00"
                    record["date_source"] = "migrated_uncertain"
                    uncertain += 1

        # Recover a start date too, but only when the parsed range's end
        # matches the end date we already trust — that agreement is what
        # makes the start believable.
        if not record.get("start_date") and record.get("end_date"):
            known_end = date.fromisoformat(record["end_date"][:10])
            parsed_start, parsed_end = extract_date_range(
                f"{record.get('title') or ''} {record.get('description') or ''}",
                reference=date.fromisoformat(record.get("first_seen") or known_end.isoformat()),
                max_date=today,
            )
            if parsed_start and parsed_end == known_end:
                record["start_date"] = f"{parsed_start.isoformat()}T00:00:00"
                starts_recovered += 1

        record.setdefault("start_date", None)
        record.setdefault("still_listed", True)
        record.setdefault("delisted_on", None)
        record.setdefault("partner_slug", None)

        record.update(classify(record))
        record.update(extract_offer_economics(record))
        record.update(compute_status(record, today))
        migrated[slug] = record

    save_state(migrated)
    insights = build_insights(migrated, today)
    save_insights(insights)

    print(f"Migrated {len(migrated)} offers.")
    print(f"  end date recovered exactly:   {exact}")
    print(f"  end date read from offer copy: {recovered_from_copy}")
    print(f"  end date uncertain (was 0):   {uncertain}")
    print(f"  open-ended, no end date:      {openended}")
    print(f"  start date read from copy:    {starts_recovered}")
    print("\nThe uncertain ones are corrected on the next scrape.")
    print_report(insights)


if __name__ == "__main__":
    migrate()

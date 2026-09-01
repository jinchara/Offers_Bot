"""
offer_status.py
Single source of truth for "is this offer live right now?".

WHY THIS MODULE EXISTS
----------------------
The old code stored only `remaining_days`, computed at scrape time with
`max(days, 0)`. That created three separate bugs:

  1. An offer that ended three weeks ago and an offer that ends tonight
     both stored `remaining_days = 0`, so the UI labelled both
     "მალე იწურება". They are not the same thing.
  2. `remaining_days` is a snapshot. If the GitHub Action didn't run for
     two days, the static site showed a countdown that was two days stale.
  3. Offers that hadn't STARTED yet (TBC shows "დასაწყისი: 25 აგვისტო")
     were counted as active.

The fix: persist the raw `start_date` / `end_date` from the API and derive
status on demand — in Python for reports, and again in JavaScript for the
dashboard, so the countdown is correct even between scrapes.

STATUS VALUES
-------------
  upcoming     startDate is in the future — announced but not live yet
  active       running, more than ENDING_SOON_DAYS left
  ending_soon  running, ENDING_SOON_DAYS or fewer left (0 = last day)
  ended        endDate has passed
  evergreen    no endDate at all — a standing partner discount

`is_live` is the flag analysis should filter on: True for
active / ending_soon / evergreen, False for upcoming / ended.
"""

from datetime import date, datetime

ENDING_SOON_DAYS = 3

LIVE_STATUSES = frozenset({"active", "ending_soon", "evergreen"})

STATUS_LABELS_KA = {
    "upcoming": "ჯერ არ დაწყებულა",
    "active": "აქტიური",
    "ending_soon": "მალე იწურება",
    "ended": "დასრულებული",
    "evergreen": "მუდმივი",
}


def parse_api_date(value):
    """
    Parses the API's date strings into a `date`.

    TBC sends naive ISO timestamps like '2026-08-11T23:59:00'. Some records
    carry a 'Z' suffix or an explicit offset, which `fromisoformat` rejects
    on Python < 3.11, so those are normalised first. Returns None on
    anything unparseable rather than raising — a malformed date on one
    offer must not kill the whole run.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    # Drop a trailing timezone offset (+04:00 / -0500) — TBC's dates are
    # all Tbilisi local time and we only care about day granularity.
    for sep in ("+", "-"):
        tail = text[10:]  # never touch the date part itself
        idx = tail.find(sep)
        if idx != -1 and ":" in tail:
            text = text[:10] + tail[:idx]
            break
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def compute_status(offer: dict, today: date | None = None) -> dict:
    """
    Derives live status from an offer's raw dates.

    Returns keys that are safe to merge straight into the offer record:
      status, status_label, is_live, days_left, days_until_start,
      duration_days
    """
    today = today or date.today()
    start = parse_api_date(offer.get("start_date"))
    end = parse_api_date(offer.get("end_date"))

    days_left = (end - today).days if end else None
    days_until_start = (start - today).days if start else None
    duration_days = (end - start).days + 1 if (start and end and end >= start) else None

    if end and days_left < 0:
        status = "ended"
    elif start and days_until_start > 0:
        status = "upcoming"
    elif end is None:
        status = "evergreen"
    elif days_left <= ENDING_SOON_DAYS:
        status = "ending_soon"
    else:
        status = "active"

    return {
        "status": status,
        "status_label": STATUS_LABELS_KA[status],
        "is_live": status in LIVE_STATUSES,
        "days_left": days_left,
        "days_until_start": days_until_start,
        "duration_days": duration_days,
    }


def live_offers(offers, today: date | None = None) -> list[dict]:
    """Filters to offers a customer could actually use today."""
    return [o for o in offers if compute_status(o, today)["is_live"]]


def days_left_label(days_left) -> str:
    """Georgian countdown text. TBC's own site counts the last day as 1."""
    if days_left is None:
        return "ვადის გარეშე"
    if days_left < 0:
        return "დასრულებული"
    if days_left == 0:
        return "ბოლო დღე"
    return f"დარჩა {days_left} დღე"

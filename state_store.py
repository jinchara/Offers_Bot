"""
state_store.py
Read/write helpers for everything the bot persists:

  data/offers.json     every offer we've ever seen, keyed by slug
  data/history.jsonl   one line per run: counts by status
  data/insights.json   pre-computed analytics for the dashboard

WHY offers.json NOW KEEPS ENDED OFFERS
--------------------------------------
The old `main.py` rebuilt state purely from the current fetch, so the
moment TBC dropped an offer from their listing it vanished from our data
too. That made "how many offers did TBC run in July?" unanswerable — the
July offers were gone.

Now nothing is deleted. Offers that disappear from the API are kept with
`still_listed: false` and a `delisted_on` date. Analysis that cares about
what's live today filters on status; monthly and trend analysis gets the
full history. Retention is capped by ARCHIVE_RETENTION_DAYS so the file
can't grow without bound.

Writes go to a temp file and are then renamed, so a run that dies halfway
leaves the previous good state intact rather than a truncated JSON file.
"""

import json
import os
import tempfile
from datetime import date, datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STATE_FILE = os.path.join(DATA_DIR, "offers.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")
INSIGHTS_FILE = os.path.join(DATA_DIR, "insights.json")

# Delisted offers older than this are dropped. ~14 months keeps a full
# year of seasonal comparison available.
ARCHIVE_RETENTION_DAYS = 430


def _write_json_atomic(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # Better to start clean than to crash the daily run forever.
        print(f"[state_store] offers.json is corrupt ({e}); starting from empty state.")
        return {}


def save_state(state: dict) -> None:
    _write_json_atomic(STATE_FILE, state)


def prune_archive(state: dict, today: date | None = None) -> dict:
    """Drops delisted offers past the retention window."""
    today = today or date.today()
    cutoff = (today - timedelta(days=ARCHIVE_RETENTION_DAYS)).isoformat()
    return {
        slug: offer for slug, offer in state.items()
        if offer.get("still_listed", True) or (offer.get("last_seen") or "9999") >= cutoff
    }


def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    records = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def append_history(record: dict) -> None:
    """
    Appends one snapshot, replacing any earlier entry for the same date.

    The old version blind-appended, so a day with three manual re-runs
    produced three rows and the trend chart drew a flat step where there
    was really one data point. Last write for a given day wins.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    record = {"date": date.today().isoformat(), **record}

    # Collapse to one row per date, last write wins. The old version blind-
    # appended, so a day with three manual re-runs left three rows and the
    # trend chart drew a flat step where there was really one data point.
    # Existing duplicates in the file are cleaned up here too, not just
    # today's, so the history heals itself on the next run.
    by_date = {}
    for row in load_history():
        if row.get("date"):
            by_date[row["date"]] = row
    by_date[record["date"]] = record
    existing = [by_date[d] for d in sorted(by_date)]

    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in existing:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, HISTORY_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_insights(payload: dict) -> None:
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), **payload}
    _write_json_atomic(INSIGHTS_FILE, payload)


def load_insights() -> dict:
    if not os.path.exists(INSIGHTS_FILE):
        return {}
    try:
        with open(INSIGHTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

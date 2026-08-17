"""
reports.py
Generates the "interesting" layer on top of raw scraping:
  - Category breakdown (pie chart)
  - New-offers-per-day trend (bar chart)
  - A text summary sent alongside the images

Run manually or via a separate weekly/monthly GitHub Actions cron
(see .github/workflows/weekly_report.yml).

Usage:
    python reports.py weekly
    python reports.py monthly
"""

import json
import os
import sys
from collections import Counter
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")  # no display needed, just save PNGs
import matplotlib.pyplot as plt

from telegram_notify import send_message, send_photo

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STATE_FILE = os.path.join(DATA_DIR, "offers.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")
TMP_DIR = os.path.join(DATA_DIR, "tmp")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def offers_added_since(state: dict, since: date) -> list[dict]:
    return [
        o for o in state.values()
        if date.fromisoformat(o["first_seen"]) >= since
    ]


def make_category_pie(offers: list[dict], out_path: str, title: str):
    counts = Counter(o.get("category", "სხვა") for o in offers)
    if not counts:
        return False
    labels, sizes = zip(*counts.most_common())
    plt.figure(figsize=(7, 7))
    plt.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    return True


def make_trend_bar(history: list[dict], since: date, out_path: str, title: str):
    filtered = [h for h in history if date.fromisoformat(h["date"]) >= since]
    if not filtered:
        return False
    dates = [h["date"] for h in filtered]
    counts = [h["offer_count"] for h in filtered]
    plt.figure(figsize=(9, 4))
    plt.bar(dates, counts)
    plt.xticks(rotation=45, ha="right")
    plt.title(title)
    plt.ylabel("სულ აქტიური შეთავაზება")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    return True


def run_report(period: str):
    os.makedirs(TMP_DIR, exist_ok=True)
    state = load_state()
    history = load_history()

    if period == "weekly":
        since = date.today() - timedelta(days=7)
        label = "ბოლო 7 დღე"
    elif period == "monthly":
        since = date.today() - timedelta(days=30)
        label = "ბოლო 30 დღე"
    else:
        raise ValueError("period must be 'weekly' or 'monthly'")

    new_offers = offers_added_since(state, since)

    summary_lines = [
        f"📊 <b>TBC შეთავაზებების რეპორტი — {label}</b>",
        f"🆕 ახალი შეთავაზება: {len(new_offers)}",
        f"📦 სულ აქტიური ამჟამად: {len(state)}",
    ]

    top_categories = Counter(o.get("category", "სხვა") for o in new_offers).most_common(3)
    if top_categories:
        summary_lines.append("🔥 ყველაზე აქტიური კატეგორია:")
        for cat, count in top_categories:
            summary_lines.append(f"   • {cat}: {count}")

    send_message("\n".join(summary_lines))

    pie_path = os.path.join(TMP_DIR, f"{period}_categories.png")
    if make_category_pie(new_offers, pie_path, f"ახალი შეთავაზებები კატეგორიების მიხედვით ({label})"):
        send_photo(pie_path, caption="კატეგორიების განაწილება")

    trend_path = os.path.join(TMP_DIR, f"{period}_trend.png")
    if make_trend_bar(history, since, trend_path, f"აქტიური შეთავაზებების დინამიკა ({label})"):
        send_photo(trend_path, caption="დინამიკა დღეების მიხედვით")


if __name__ == "__main__":
    period = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    run_report(period)

"""
reports.py
Generates the "interesting" layer on top of raw scraping:
  - Category breakdown (donut chart)
  - New-offers-per-day trend (area/line chart)
  - Top offers by cashback % (horizontal bar chart)
  - A text summary sent alongside the images

Run manually or via a separate weekly/monthly GitHub Actions cron
(see .github/workflows/reports.yml).

Usage:
    python reports.py weekly
    python reports.py monthly
"""

import json
import os
import sys
from collections import Counter
from datetime import date, timedelta

try:
    import matplotlib
    matplotlib.use("Agg")  # no display needed, just save PNGs
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
except ImportError as e:
    print(f"Error: matplotlib is not installed. Install it with: pip install matplotlib")
    sys.exit(1)

from telegram_notify import send_message, send_photo

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STATE_FILE = os.path.join(DATA_DIR, "offers.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")
TMP_DIR = os.path.join(DATA_DIR, "tmp")

# --- Visual style ----------------------------------------------------------
# A small, modern-ish palette instead of matplotlib's default colors.
PALETTE = [
    "#6C5CE7", "#00B894", "#0984E3", "#FDCB6E", "#E17055",
    "#FD79A8", "#00CEC9", "#A29BFE", "#55EFC4", "#FAB1A0",
    "#74B9FF", "#FFEAA7", "#81ECEC", "#D63031", "#636E72",
    "#00A896", "#F94144", "#F3722C",
]
BG = "#FFFFFF"
PANEL_BG = "#F7F7FB"
TEXT_COLOR = "#2D3436"
GRID_COLOR = "#E0E0E8"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": PANEL_BG,
    "savefig.facecolor": BG,
    "text.color": TEXT_COLOR,
    "axes.edgecolor": GRID_COLOR,
    "axes.labelcolor": TEXT_COLOR,
    "xtick.color": TEXT_COLOR,
    "ytick.color": TEXT_COLOR,
    "axes.grid": True,
    "grid.color": GRID_COLOR,
    "grid.linewidth": 0.8,
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
})


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


def _truncate(text: str, max_len: int = 26) -> str:
    if not text:
        return ""
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def make_category_pie(offers: list[dict], out_path: str, title: str):
    counts = Counter(o.get("category", "სხვა") for o in offers)
    if not counts:
        return False
    labels, sizes = zip(*counts.most_common())
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]

    fig, ax = plt.subplots(figsize=(8, 7))
    wedges, _, autotexts = ax.pie(
        sizes,
        colors=colors,
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 5 else "",
        pctdistance=0.8,
        startangle=90,
        wedgeprops=dict(width=0.45, edgecolor=BG, linewidth=2),
        textprops={"color": "white", "fontweight": "bold", "fontsize": 10},
    )
    ax.set_title(title, pad=20)
    ax.legend(
        wedges, labels,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        frameon=False,
        fontsize=10,
    )
    ax.axis("equal")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


def make_trend_bar(history: list[dict], since: date, out_path: str, title: str):
    filtered = [h for h in history if date.fromisoformat(h["date"]) >= since]
    if not filtered:
        return False
    dates = [h["date"] for h in filtered]
    counts = [h["offer_count"] for h in filtered]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(dates, counts, color=PALETTE[0], linewidth=2.5, marker="o",
             markersize=6, markerfacecolor="white", markeredgewidth=2,
             markeredgecolor=PALETTE[0], zorder=3)
    ax.fill_between(range(len(dates)), counts, color=PALETTE[0], alpha=0.12, zorder=1)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(dates, rotation=45, ha="right")
    ax.set_title(title, pad=15)
    ax.set_ylabel("სულ აქტიური შეთავაზება")
    ax.grid(axis="y", linestyle="--", alpha=0.6)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


def make_top_cashback_bar(state: dict, out_path: str, title: str, top_n: int = 10):
    """
    Horizontal bar chart of the top N *currently active* offers by cashback
    percentage. Each bar is annotated with the percent and, if known,
    whether the cashback is unlimited or capped at a specific amount.
    """
    candidates = [o for o in state.values() if o.get("cashback_percent")]
    if not candidates:
        return False

    candidates = sorted(candidates, key=lambda o: o["cashback_percent"], reverse=True)[:top_n]
    # Reverse so the highest percent renders at the top of the barh chart
    candidates = candidates[::-1]

    labels = [_truncate(o.get("title") or o.get("slug", "")) for o in candidates]
    values = [o["cashback_percent"] for o in candidates]

    colors = []
    for v in values:
        # Gradient from the palette's cool end (low %) to warm end (high %)
        t = v / 100
        colors.append(PALETTE[min(int(t * (len(PALETTE) - 1)), len(PALETTE) - 1)])

    fig, ax = plt.subplots(figsize=(9, max(4, 0.55 * len(candidates) + 1)))
    bars = ax.barh(labels, values, color=colors, height=0.65, zorder=3)

    for bar, offer, value in zip(bars, candidates, values):
        if offer.get("cap_unlimited"):
            note = "ულიმიტოდ"
        elif offer.get("cap_amount") is not None:
            note = f"მაქს. {offer['cap_amount']:g} GEL"
        else:
            note = ""
        label = f"{value}%" + (f"  ·  {note}" if note else "")
        ax.text(
            bar.get_width() + max(values) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center", fontsize=9.5, color=TEXT_COLOR,
        )

    ax.set_xlim(0, max(values) * 1.35)
    ax.set_xlabel("ქეშბექი, %")
    ax.set_title(title, pad=15)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
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

    cashback_path = os.path.join(TMP_DIR, f"{period}_top_cashback.png")
    if make_top_cashback_bar(state, cashback_path, "საუკეთესო ქეშბექი — აქტიური შეთავაზებები"):
        send_photo(cashback_path, caption="ტოპ შეთავაზებები ქეშბექის მიხედვით")


if __name__ == "__main__":
    period = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    run_report(period)
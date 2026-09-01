"""
reports.py
Weekly and monthly Telegram reports with charts.

    python reports.py weekly
    python reports.py monthly

THE WEEKLY / MONTHLY DISTINCTION
--------------------------------
These two reports answer different questions and therefore use different
populations. Getting this wrong is what made the old numbers untrustworthy.

  weekly  — "what is TBC offering right now, and what moved this week?"
            Snapshot charts count LIVE offers only. A campaign that ended
            on Tuesday does not belong in Sunday's average cashback.

  monthly — "what did TBC do over the last 30 days?"
            Counts every offer that was RUNNING at any point in the
            window, ended or not. Excluding finished campaigns here would
            hide most of the month's activity, since the median campaign
            only lasts about a week.

Both reports state their population in the message, so nobody has to guess
which one they're reading.
"""

import logging
import os
import sys
from collections import Counter
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")  # headless: just write PNGs
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from fontTools.ttLib import TTFont

from analytics import build_insights, split_by_status, _was_running_between
from offer_status import parse_api_date
from state_store import load_history, load_state
from telegram_notify import send_message, send_photo

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TMP_DIR = os.path.join(DATA_DIR, "tmp")

# --- Visual style ----------------------------------------------------------
PALETTE = [
    "#ff5c0a", "#091A2B", "#CDA176", "#3d6b8a", "#00B894",
    "#6C5CE7", "#0984E3", "#FDCB6E", "#E17055", "#FD79A8",
    "#00CEC9", "#A29BFE", "#55EFC4", "#FAB1A0", "#74B9FF",
    "#81ECEC", "#D63031", "#636E72", "#00A896",
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

# --- Georgian font handling ------------------------------------------------
# matplotlib's default (DejaVu Sans) has no Georgian glyphs, so every label
# renders as a row of empty boxes. Setting rcParams to a font name that
# isn't installed doesn't help either — matplotlib silently falls back and
# floods the log with findfont warnings.
#
# So: inspect the installed fonts and pick one that genuinely contains the
# Georgian block. If nothing on the machine does, transliterate the chart
# labels to Latin instead of shipping unreadable boxes.
#
# The workflow installs fonts-noto-core, which provides Noto Sans Georgian.

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

GEORGIAN_TEST_CHAR = "ა"      # U+10D0
LARI_SIGN = "₾"               # U+20BE, missing from many fonts


def _font_supports(font_path: str, char: str) -> bool:
    try:
        return TTFont(font_path, fontNumber=0, lazy=True).getBestCmap().get(ord(char)) is not None
    except Exception:
        return False


def _pick_georgian_font():
    """Returns (font_name, supports_lari) or (None, False) if none found."""
    preferred = ("Noto Sans Georgian", "DejaVu Sans", "FreeSans", "Liberation Sans")
    installed = {}
    for entry in fm.fontManager.ttflist:
        installed.setdefault(entry.name, entry.fname)

    ordered = [n for n in preferred if n in installed] + \
              [n for n in installed if n not in preferred]

    for name in ordered:
        path = installed[name]
        if _font_supports(path, GEORGIAN_TEST_CHAR):
            return name, _font_supports(path, LARI_SIGN)
    return None, False


GEORGIAN_FONT, SUPPORTS_LARI = _pick_georgian_font()

if GEORGIAN_FONT:
    plt.rcParams["font.family"] = GEORGIAN_FONT
else:
    print(
        "WARNING: no installed font covers Georgian. Chart labels will be "
        "transliterated. Install fonts-noto-core to fix "
        "(the GitHub workflow already does this)."
    )

# Currency symbol that will actually render.
GEL = LARI_SIGN if SUPPORTS_LARI else " GEL"

# Minimal transliteration, used only when no Georgian font exists. Better a
# readable approximation than a chart full of tofu boxes.
_TRANSLIT = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
    "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
    "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "f",
    "ქ": "q", "ღ": "gh", "ყ": "y", "შ": "sh", "ჩ": "ch", "ც": "ts",
    "ძ": "dz", "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
}


def label(text) -> str:
    """Chart-safe label: passed through as-is when a Georgian font exists."""
    text = str(text or "")
    if GEORGIAN_FONT:
        return text
    return "".join(_TRANSLIT.get(ch, ch) for ch in text)


def _truncate(text: str, max_len: int = 26) -> str:
    if not text:
        return ""
    text = label(text)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _save(fig, out_path):
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


# =========================================================================
# charts
# =========================================================================

def make_category_donut(offers, out_path, title):
    counts = Counter(o.get("category") or "სხვა" for o in offers)
    if not counts:
        return False
    labels, sizes = zip(*counts.most_common(12))
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]

    fig, ax = plt.subplots(figsize=(8, 7))
    wedges, _, _ = ax.pie(
        sizes,
        colors=colors,
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 5 else "",
        pctdistance=0.8,
        startangle=90,
        wedgeprops=dict(width=0.45, edgecolor=BG, linewidth=2),
        textprops={"color": "white", "fontweight": "bold", "fontsize": 10},
    )
    ax.set_title(label(title), pad=20)
    ax.legend(wedges, [label(x) for x in labels], loc="center left", bbox_to_anchor=(1.02, 0.5),
              frameon=False, fontsize=10)
    ax.axis("equal")
    return _save(fig, out_path)


def make_trend_chart(history, since, out_path, title):
    """
    Active-offer count over time.

    History rows written before this version only have `offer_count`, which
    counted everything in the file including ended offers. Newer rows carry
    `live`. Prefer `live` and fall back, so old and new rows plot together
    without a discontinuity.
    """
    rows = [h for h in history if h.get("date") and date.fromisoformat(h["date"]) >= since]
    if not rows:
        return False
    rows.sort(key=lambda h: h["date"])
    dates = [h["date"][5:] for h in rows]
    counts = [h.get("live", h.get("offer_count", 0)) for h in rows]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(dates, counts, color=PALETTE[0], linewidth=2.5, marker="o",
            markersize=6, markerfacecolor="white", markeredgewidth=2,
            markeredgecolor=PALETTE[0], zorder=3)
    ax.fill_between(range(len(dates)), counts, color=PALETTE[0], alpha=0.12, zorder=1)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(dates, rotation=45, ha="right")
    ax.set_title(label(title), pad=15)
    ax.set_ylabel(label("აქტიური შეთავაზება"))
    ax.grid(axis="y", linestyle="--", alpha=0.6)
    ax.grid(axis="x", visible=False)
    return _save(fig, out_path)


def make_top_cashback_bar(offers, out_path, title, top_n=10):
    """Top offers by cashback, annotated with the cap where we know it."""
    candidates = [o for o in offers if o.get("cashback_percent")]
    if not candidates:
        return False
    candidates.sort(key=lambda o: o["cashback_percent"], reverse=True)
    candidates = candidates[:top_n][::-1]  # reversed so the biggest sits on top

    labels = [_truncate(o.get("brand") or o.get("title") or o.get("slug", "")) for o in candidates]
    values = [o["cashback_percent"] for o in candidates]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(values))]

    fig, ax = plt.subplots(figsize=(9, max(4, 0.55 * len(candidates) + 1)))
    bars = ax.barh(labels, values, color=colors, height=0.65, zorder=3)

    for bar, offer, value in zip(bars, candidates, values):
        if offer.get("cap_unlimited"):
            note = label("ულიმიტოდ")
        elif offer.get("cap_amount") is not None:
            note = label("მაქს.") + f" {offer['cap_amount']:g}{GEL}"
        else:
            note = ""
        ax.text(bar.get_width() + max(values) * 0.02,
                bar.get_y() + bar.get_height() / 2,
                f"{value}%" + (f"  ·  {note}" if note else ""),
                va="center", fontsize=9.5, color=TEXT_COLOR)

    ax.set_xlim(0, max(values) * 1.35)
    ax.set_xlabel(label("ქეშბექი, %"))
    ax.set_title(label(title), pad=15)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    ax.grid(axis="y", visible=False)
    return _save(fig, out_path)


def make_duration_chart(offers, out_path, title):
    """How long campaigns run. Open-ended offers are excluded, not bucketed."""
    buckets = {"1–3": 0, "4–7": 0, "8–14": 0, "15–30": 0, "31+": 0}
    for offer in offers:
        start = parse_api_date(offer.get("start_date"))
        end = parse_api_date(offer.get("end_date"))
        if not (start and end and end >= start):
            continue
        days = (end - start).days + 1
        if days <= 3:
            buckets["1–3"] += 1
        elif days <= 7:
            buckets["4–7"] += 1
        elif days <= 14:
            buckets["8–14"] += 1
        elif days <= 30:
            buckets["15–30"] += 1
        else:
            buckets["31+"] += 1

    if not sum(buckets.values()):
        return False

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar([label(k) for k in buckets.keys()], list(buckets.values()),
                  color=PALETTE[0], width=0.6, zorder=3)
    ax.bar_label(bars, padding=3, fontsize=10)
    ax.set_title(label(title), pad=15)
    ax.set_xlabel(label("კამპანიის ხანგრძლივობა (დღე)"))
    ax.set_ylabel(label("კამპანიების რაოდენობა"))
    ax.grid(axis="y", linestyle="--", alpha=0.6)
    ax.grid(axis="x", visible=False)
    return _save(fig, out_path)


# =========================================================================
# report bodies
# =========================================================================

def _summary_lines(period, label, population_note, insights, window):
    snap = insights["snapshot"]
    lines = [
        f"📊 <b>TBC შეთავაზებების რეპორტი — {label}</b>",
        f"<i>{population_note}</i>",
        "",
        f"📦 აქტიური ახლა: {snap['live']}"
        f" (პარტნიორები: {snap['live_merchant_offers']})",
        f"🗓 დაანონსებული: {snap['upcoming']}   ⌛️ არქივში: {snap['ended']}",
        f"🆕 გაშვებული {label}-ში: {window['launched']}",
        f"⌛️ დასრულებული {label}-ში: {window['ended']}"
        f"   (სუფთა ცვლილება: {window['net_change']:+d})",
    ]
    if snap["avg_cashback"] is not None:
        lines.append(
            f"💰 საშ. ქეშბექი აქტიურებში: {snap['avg_cashback']}%"
            f" (მედიანა {snap['median_cashback']}%, მაქს. {snap['max_cashback']}%)"
        )

    top = window["top_categories"][:3]
    if top:
        lines.append("")
        lines.append("🔥 ყველაზე აქტიური კატეგორიები:")
        lines += [f"   • {row['label']}: {row['value']}" for row in top]

    camp = insights["campaigns"]
    if camp["median_duration_days"]:
        lines.append("")
        lines.append(
            f"⏱ მედიანური კამპანია: {camp['median_duration_days']} დღე"
            f" · {camp['flash_share']}% არის 3 დღე ან ნაკლები"
        )

    thin = insights["categories"]["uncovered"] + insights["categories"]["thin"]
    if thin:
        lines.append("")
        lines.append("🕳 სუსტი კატეგორიები (0–2 აქტიური): " + ", ".join(thin[:6]))

    movements = insights["rate_movements"][:3]
    if movements:
        lines.append("")
        lines.append("📈 ქეშბექის ცვლილებები:")
        for m in movements:
            lines.append(f"   • {m['brand']}: {m['from']}% → {m['to']}%")

    quality = insights["data_quality"]
    lines.append("")
    lines.append(
        f"ℹ️ კატეგორიები დათვლილია ავტომატურად — {quality['categorised_share']}% "
        f"დადგენილია, დანარჩენი „სხვა“-შია."
    )
    return lines


def run_report(period: str):
    os.makedirs(TMP_DIR, exist_ok=True)
    state = load_state()
    if not state:
        send_message("⚠️ data/offers.json ცარიელია — ჯერ გაუშვი <code>python main.py</code>.")
        return

    history = load_history()
    today = date.today()
    insights = build_insights(state, today)
    all_offers = list(state.values())

    if period == "weekly":
        days, label = 7, "ბოლო 7 დღე"
        window = insights["last_7_days"]
        # Snapshot charts: what a customer can use today.
        chart_offers = [o for o in split_by_status(all_offers, today)[0] if not o.get("bank_product")]
        population_note = "დიაგრამები ეხება მხოლოდ ამჟამად აქტიურ პარტნიორულ შეთავაზებებს"
    elif period == "monthly":
        days, label = 30, "ბოლო 30 დღე"
        window = insights["last_30_days"]
        # Activity charts: everything that ran in the window, ended or not.
        since = today - timedelta(days=days)
        chart_offers = [
            o for o in all_offers
            if not o.get("bank_product") and _was_running_between(o, since, today)
        ]
        population_note = (
            "დიაგრამები ეხება ყველა შეთავაზებას, რომელიც ამ პერიოდში მოქმედებდა "
            "— დასრულებულების ჩათვლით"
        )
    else:
        raise ValueError("period must be 'weekly' or 'monthly'")

    send_message("\n".join(_summary_lines(period, label, population_note, insights, window)))

    since = today - timedelta(days=days)

    donut = os.path.join(TMP_DIR, f"{period}_categories.png")
    if make_category_donut(chart_offers, donut, f"კატეგორიები — {label}"):
        send_photo(donut, caption=f"კატეგორიების განაწილება ({len(chart_offers)} შეთავაზება)")

    trend = os.path.join(TMP_DIR, f"{period}_trend.png")
    if make_trend_chart(history, since, trend, f"აქტიური შეთავაზებები — {label}"):
        send_photo(trend, caption="დინამიკა დღეების მიხედვით")

    cashback = os.path.join(TMP_DIR, f"{period}_top_cashback.png")
    if make_top_cashback_bar(chart_offers, cashback, "საუკეთესო ქეშბექი"):
        send_photo(cashback, caption="ტოპ შეთავაზებები ქეშბექის მიხედვით")

    if period == "monthly":
        duration = os.path.join(TMP_DIR, "monthly_duration.png")
        if make_duration_chart(chart_offers, duration, "კამპანიების ხანგრძლივობა"):
            send_photo(duration, caption="რამდენ ხანს გრძელდება თიბისის აქციები")


if __name__ == "__main__":
    run_report(sys.argv[1] if len(sys.argv) > 1 else "weekly")

"""
analytics.py
Turns the raw offer store into the numbers a competitive-intelligence
squad actually asks for, and writes them to data/insights.json.

The guiding rule, and the thing the old code got wrong:

    Anything describing the market RIGHT NOW counts only live offers.
    Anything describing ACTIVITY OVER A PERIOD counts every offer that
    was running in that period, ended or not.

So "average cashback TBC is offering" excludes the campaign that finished
in November, but "how many campaigns did TBC launch in November" obviously
includes it. Mixing the two is what made the old dashboard read 541 active
offers when a chunk of them were long finished.

Run standalone for a text audit:
    python analytics.py
"""

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from categorize import OTHER, TBC_CATEGORIES
from offer_status import compute_status, parse_api_date

FLASH_CAMPAIGN_MAX_DAYS = 3


# =========================================================================
# helpers
# =========================================================================

def _median(values):
    return round(statistics.median(values), 1) if values else None


def _mean(values):
    return round(statistics.fmean(values), 1) if values else None


def _counter_to_rows(counter: Counter, limit: int | None = None):
    rows = [{"label": k, "value": v} for k, v in counter.most_common(limit)]
    return rows


def _was_running_between(offer, start: date, end: date) -> bool:
    """True if the offer's window overlaps [start, end] at all."""
    offer_start = parse_api_date(offer.get("start_date"))
    offer_end = parse_api_date(offer.get("end_date"))
    if offer_end and offer_end < start:
        return False
    if offer_start and offer_start > end:
        return False
    if not offer_start and not offer_end:
        # Open-ended offer: count it only if we'd already seen it by `end`.
        first_seen = parse_api_date(offer.get("first_seen"))
        return bool(first_seen and first_seen <= end)
    return True


def split_by_status(offers, today: date | None = None):
    """Returns (live, upcoming, ended)."""
    live, upcoming, ended = [], [], []
    for offer in offers:
        status = offer.get("status") or compute_status(offer, today)["status"]
        if status == "ended":
            ended.append(offer)
        elif status == "upcoming":
            upcoming.append(offer)
        else:
            live.append(offer)
    return live, upcoming, ended


# =========================================================================
# individual insight blocks
# =========================================================================

def market_snapshot(live, upcoming, ended, merchant_only):
    """What a customer can use today."""
    cashbacks = [o["cashback_percent"] for o in merchant_only if o.get("cashback_percent")]
    caps = [o["cap_amount"] for o in merchant_only if o.get("cap_amount")]
    return {
        "live": len(live),
        "upcoming": len(upcoming),
        "ended": len(ended),
        "live_merchant_offers": len(merchant_only),
        "live_bank_product_offers": len(live) - len(merchant_only),
        "avg_cashback": _mean(cashbacks),
        "median_cashback": _median(cashbacks),
        "max_cashback": max(cashbacks) if cashbacks else None,
        "offers_with_cashback": len(cashbacks),
        "unlimited_cap_share": round(
            100 * sum(1 for o in merchant_only if o.get("cap_unlimited")) / len(merchant_only), 1
        ) if merchant_only else None,
        "avg_cap_amount": round(statistics.fmean(caps)) if caps else None,
        "median_cap_amount": round(statistics.median(caps)) if caps else None,
    }


def category_breakdown(live_merchant):
    """
    Per-category depth and generosity, plus the categories TBC is NOT
    covering — the empty rows are the interesting ones for a competitor.
    """
    by_cat = defaultdict(list)
    for offer in live_merchant:
        by_cat[offer.get("category") or OTHER].append(offer)

    rows = []
    for category in TBC_CATEGORIES + [OTHER]:
        bucket = by_cat.get(category, [])
        cashbacks = [o["cashback_percent"] for o in bucket if o.get("cashback_percent")]
        rows.append({
            "category": category,
            "live_offers": len(bucket),
            "share": round(100 * len(bucket) / len(live_merchant), 1) if live_merchant else 0,
            "avg_cashback": _mean(cashbacks),
            "max_cashback": max(cashbacks) if cashbacks else None,
            "distinct_brands": len({o.get("brand") for o in bucket if o.get("brand")}),
        })
    rows.sort(key=lambda r: r["live_offers"], reverse=True)

    return {
        "rows": rows,
        "uncovered": [r["category"] for r in rows if r["live_offers"] == 0],
        "thin": [r["category"] for r in rows if 0 < r["live_offers"] <= 2],
    }


def merchant_concentration(all_offers):
    """
    How dependent TBC's offer wall is on a handful of partners, and which
    partners come back again and again.
    """
    per_brand = Counter(o.get("brand") for o in all_offers if o.get("brand"))
    total = sum(per_brand.values())
    top10 = per_brand.most_common(10)
    repeat = {b: c for b, c in per_brand.items() if c > 1}
    return {
        "distinct_brands": len(per_brand),
        "top_partners": [{"brand": b, "offers": c} for b, c in top10],
        "top10_share": round(100 * sum(c for _, c in top10) / total, 1) if total else 0,
        "repeat_partner_count": len(repeat),
        "repeat_partner_share": round(100 * len(repeat) / len(per_brand), 1) if per_brand else 0,
        "one_off_partners": sum(1 for c in per_brand.values() if c == 1),
    }


def campaign_shape(all_offers):
    """
    Duration and timing patterns — the tactical read. Flash campaigns and
    weekday clustering tell you how TBC actually runs promotions, which is
    harder to copy from a screenshot than a cashback number.
    """
    durations, weekdays, months = [], Counter(), Counter()
    flash = evergreen = 0

    for offer in all_offers:
        start = parse_api_date(offer.get("start_date"))
        end = parse_api_date(offer.get("end_date"))
        if end is None:
            evergreen += 1
        if start and end and end >= start:
            days = (end - start).days + 1
            durations.append(days)
            if days <= FLASH_CAMPAIGN_MAX_DAYS:
                flash += 1
        if start:
            weekdays[start.weekday()] += 1
            months[start.strftime("%Y-%m")] += 1

    weekday_names = ["ორშ", "სამ", "ოთხ", "ხუთ", "პარ", "შაბ", "კვი"]
    dated = len(durations)

    return {
        "dated_campaigns": dated,
        "evergreen_offers": evergreen,
        "avg_duration_days": _mean(durations),
        "median_duration_days": _median(durations),
        "flash_campaigns": flash,
        "flash_share": round(100 * flash / dated, 1) if dated else None,
        "launches_by_weekday": [
            {"label": weekday_names[i], "value": weekdays.get(i, 0)} for i in range(7)
        ],
        "launches_by_month": [
            {"label": m, "value": months[m]} for m in sorted(months)
        ][-12:],
    }


def _backfill_date(all_offers):
    """
    The day the tracker first ran. Every pre-existing offer got that day as
    its `first_seen`, which does NOT mean they all launched then — treating
    it as a launch date reports the entire back catalogue as brand new.
    """
    seen = [o.get("first_seen") for o in all_offers if o.get("first_seen")]
    return min(seen) if seen else None


def period_activity(all_offers, days: int, today: date | None = None):
    """Launches, endings, and net change over a trailing window."""
    today = today or date.today()
    since = today - timedelta(days=days)
    backfill = _backfill_date(all_offers)

    launched = ended = 0
    for offer in all_offers:
        start = parse_api_date(offer.get("start_date"))
        if start is None and offer.get("first_seen") != backfill:
            # No published start date: the day we first saw it is the best
            # proxy — except for the backfill cohort, which we skip.
            start = parse_api_date(offer.get("first_seen"))
        end = parse_api_date(offer.get("end_date"))
        if start and since <= start <= today:
            launched += 1
        if end and since <= end <= today:
            ended += 1

    running = [o for o in all_offers if _was_running_between(o, since, today)]
    cashbacks = [o["cashback_percent"] for o in running if o.get("cashback_percent")]

    return {
        "window_days": days,
        "since": since.isoformat(),
        "launched": launched,
        "ended": ended,
        "net_change": launched - ended,
        "offers_running_in_window": len(running),
        "avg_cashback_in_window": _mean(cashbacks),
        "top_categories": _counter_to_rows(
            Counter(o.get("category") or OTHER for o in running), 5
        ),
    }


def rate_movements(all_offers):
    """
    Merchants that changed their cashback rate, read off cashback_history.
    A partner going 15% -> 25% is a competitive signal worth a Slack ping.
    """
    movements = []
    for offer in all_offers:
        history = [h for h in (offer.get("cashback_history") or []) if h.get("percent")]
        if len(history) < 2:
            continue
        first, last = history[0], history[-1]
        if first["percent"] == last["percent"]:
            continue
        movements.append({
            "brand": offer.get("brand"),
            "title": offer.get("title"),
            "category": offer.get("category"),
            "from": first["percent"],
            "to": last["percent"],
            "delta": last["percent"] - first["percent"],
            "changed_on": last.get("date"),
        })
    movements.sort(key=lambda m: abs(m["delta"]), reverse=True)
    return movements[:20]


def pipeline(live, upcoming, today: date | None = None):
    """Two watchlists: about to expire, and announced but not yet live."""
    today = today or date.today()

    ending = sorted(
        (o for o in live if o.get("days_left") is not None and o["days_left"] <= 7),
        key=lambda o: o["days_left"],
    )
    starting = sorted(
        upcoming,
        key=lambda o: o.get("days_until_start") if o.get("days_until_start") is not None else 999,
    )

    def row(offer, key):
        return {
            "brand": offer.get("brand"),
            "title": offer.get("title"),
            "category": offer.get("category"),
            "cashback_percent": offer.get("cashback_percent"),
            "url": offer.get("url"),
            key: offer.get(key),
        }

    return {
        "ending_within_7_days": [row(o, "days_left") for o in ending[:25]],
        "starting_soon": [row(o, "days_until_start") for o in starting[:25]],
    }


def data_quality(all_offers):
    """
    Honesty panel. Categories are inferred, so the dashboard says how much
    of it is inferred and how confidently. Nobody should present a chart to
    a squad without knowing this number.
    """
    sources = Counter(o.get("category_source") or "unknown" for o in all_offers)
    confidence = Counter(o.get("category_confidence") or "unknown" for o in all_offers)
    unresolved = [
        {"brand": o.get("brand"), "title": o.get("title"), "slug": o.get("slug")}
        for o in all_offers if (o.get("category") or OTHER) == OTHER
    ]
    total = len(all_offers) or 1
    return {
        "total_offers": len(all_offers),
        "by_source": dict(sources),
        "by_confidence": dict(confidence),
        "categorised_share": round(100 * (total - len(unresolved)) / total, 1),
        "missing_end_date": sum(1 for o in all_offers if not o.get("end_date")),
        "unresolved_sample": sorted(
            unresolved, key=lambda r: (r["brand"] or "")
        )[:40],
    }


# =========================================================================
# entry point
# =========================================================================

def build_insights(state: dict, today: date | None = None) -> dict:
    today = today or date.today()
    all_offers = list(state.values())

    live, upcoming, ended = split_by_status(all_offers, today)
    live_merchant = [o for o in live if not o.get("bank_product")]

    return {
        "as_of": today.isoformat(),
        "snapshot": market_snapshot(live, upcoming, ended, live_merchant),
        "categories": category_breakdown(live_merchant),
        "merchants": merchant_concentration(all_offers),
        "campaigns": campaign_shape(all_offers),
        "last_7_days": period_activity(all_offers, 7, today),
        "last_30_days": period_activity(all_offers, 30, today),
        "rate_movements": rate_movements(all_offers),
        "pipeline": pipeline(live, upcoming, today),
        "channels": _counter_to_rows(
            Counter(o.get("channel") or "instore" for o in live_merchant)
        ),
        "offer_types": _counter_to_rows(
            Counter(o.get("offer_type") or "other" for o in live_merchant)
        ),
        "data_quality": data_quality(all_offers),
    }


def print_report(insights: dict) -> None:
    """Human-readable audit, handy in CI logs and for a quick sanity check."""
    snap = insights["snapshot"]
    print(f"\n=== TBC offers — {insights['as_of']} ===")
    print(f"Live: {snap['live']}   Upcoming: {snap['upcoming']}   Ended: {snap['ended']}")
    print(f"Live merchant offers: {snap['live_merchant_offers']} "
          f"(+{snap['live_bank_product_offers']} TBC product promos)")
    print(f"Cashback among live: avg {snap['avg_cashback']}%  "
          f"median {snap['median_cashback']}%  max {snap['max_cashback']}%")

    print("\nTop categories (live merchant offers):")
    for row in insights["categories"]["rows"][:8]:
        if row["live_offers"]:
            print(f"  {row['live_offers']:4d}  {row['category']:<28} "
                  f"avg {row['avg_cashback'] or '-'}%")
    if insights["categories"]["uncovered"]:
        print("  No live offers at all in:", ", ".join(insights["categories"]["uncovered"]))

    camp = insights["campaigns"]
    print(f"\nCampaign shape: median {camp['median_duration_days']} days, "
          f"{camp['flash_share']}% are {FLASH_CAMPAIGN_MAX_DAYS} days or shorter, "
          f"{camp['evergreen_offers']} open-ended")

    week = insights["last_7_days"]
    print(f"Last 7 days: +{week['launched']} launched, -{week['ended']} ended "
          f"(net {week['net_change']:+d})")

    quality = insights["data_quality"]
    print(f"\nData quality: {quality['categorised_share']}% categorised, "
          f"sources {quality['by_source']}")


if __name__ == "__main__":
    from state_store import load_state
    print_report(build_insights(load_state()))

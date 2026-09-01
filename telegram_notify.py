"""
telegram_notify.py
Sends messages/photos to your own Telegram chat via the free Bot API.

Setup (one-time, ~2 minutes, totally free):
1. In Telegram, message @BotFather -> /newbot -> follow prompts.
   You'll get a token like "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11".
2. Message your new bot anything (e.g. "hi") so it can message you back.
3. Visit https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates in a browser
   and find your numeric "chat":{"id": ...} — that's your TELEGRAM_CHAT_ID.
4. Store both as GitHub Actions secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
"""

import os

from offer_status import days_left_label

try:
    import requests  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback for minimal environments
    requests = None

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_BASE = "https://api.telegram.org"


def send_message(text: str, parse_mode: str = "HTML"):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    url = f"{API_BASE}/bot{TOKEN}/sendMessage"
    # Telegram caps messages at 4096 chars; split if needed.
    for i in range(0, len(text), 4000):
        chunk = text[i : i + 4000]
        resp = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": chunk, "parse_mode": parse_mode},
            timeout=15,
        )
        resp.raise_for_status()


def send_photo(photo_path: str, caption: str = ""):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    url = f"{API_BASE}/bot{TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        resp = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=30,
        )
    resp.raise_for_status()


def format_new_offer_message(offer: dict, category: str, economics: dict | None = None) -> str:
    # Must read the derived status, never `remaining_days`. That field can
    # be negative for a finished offer, which used to render as the
    # nonsense line "დარჩენილი დღეები: -4".
    if offer.get("status") == "upcoming":
        days_line = f"🗓 იწყება: {offer.get('start_date', '')[:10]}\n"
    else:
        label = days_left_label(offer.get("days_left"))
        days_line = f"⏳ {label}\n"

    cashback_line = ""
    if economics and economics.get("cashback_percent") is not None:
        cashback_line = f"💰 ქეშბექი: {economics['cashback_percent']}%"
        if economics.get("cap_unlimited"):
            cashback_line += " (ულიმიტოდ)"
        elif economics.get("cap_amount") is not None:
            cashback_line += f" (მაქს. {economics['cap_amount']:g}₾)"
        cashback_line += "\n"

    return (
        f"🆕 <b>ახალი შეთავაზება!</b>\n\n"
        f"🏷 {offer.get('title')}\n"
        f"🏬 {offer.get('brand') or '—'}\n"
        f"📂 კატეგორია: {category}\n"
        f"{cashback_line}"
        f"{days_line}"
        f"🔗 {offer.get('url')}"
    )


def format_price_change_message(offer: dict, old_percent: int, new_percent: int) -> str:
    direction = "📈" if new_percent > old_percent else "📉"
    verb = "გაიზარდა" if new_percent > old_percent else "შემცირდა"
    return (
        f"{direction} <b>ქეშბექი {verb}!</b>\n\n"
        f"🏷 {offer.get('title')}\n"
        f"🔁 {old_percent}% → {new_percent}%\n"
        f"🔗 {offer.get('url')}"
    )


def format_ending_soon_message(offers: list) -> str:
    """
    Digest of offers about to finish.

    Callers must pass live offers only. "დარჩენილია 0 დღე" was both ugly
    and ambiguous — it read the same for "last day" and "already over" —
    so the wording now comes from days_left_label.
    """
    lines = ["⏳ <b>მალე სრულდება:</b>"]
    for o in sorted(offers, key=lambda x: x.get("days_left") or 0):
        lines.append(f"• {o.get('title')} — {days_left_label(o.get('days_left'))}")
    return "\n".join(lines)


def format_upcoming_message(offers: list) -> str:
    """Announced but not yet running — worth knowing about in advance."""
    lines = ["🗓 <b>დაანონსებული შეთავაზებები:</b>"]
    for o in sorted(offers, key=lambda x: x.get("days_until_start") or 0):
        starts = (o.get("start_date") or "")[:10]
        lines.append(f"• {o.get('title')} — {starts}")
    return "\n".join(lines)
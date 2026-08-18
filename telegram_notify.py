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
    days = offer.get("remaining_days")
    days_line = f"⏳ დარჩენილი დღეები: {days}\n" if days is not None else ""

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
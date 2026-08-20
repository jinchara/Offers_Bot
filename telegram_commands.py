"""
telegram_commands.py
Polls Telegram for commands sent to your bot and replies using data from
the current offers state (data/offers.json).

IMPORTANT — this is polling, not a live/instant bot:
GitHub Actions can't run a persistent process to receive Telegram's
webhook in real time. Instead, this script is run periodically (see
.github/workflows/telegram_commands.yml, every ~10 minutes) and asks
Telegram "any new messages since last time?" via getUpdates. That means
replies can take anywhere from ~seconds to ~15-20 minutes depending on
GitHub's scheduler load — it's "pretty responsive", not instant.

Supported commands:
  /help                - list commands
  /latest [N]          - N most recently added offers (default 5)
  /top10               - top 10 currently active offers by cashback %
  /category <name>     - offers matching a category (partial match)
  /ending              - offers ending within the next few days
"""

import json
import os

try:
    import requests  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback for minimal environments
    requests = None

from telegram_notify import TOKEN, CHAT_ID, API_BASE, send_message
from state_store import load_state
from categorize import CATEGORY_KEYWORDS

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OFFSET_FILE = os.path.join(DATA_DIR, "telegram_offset.json")
ENDING_SOON_THRESHOLD = 3


def _load_offset() -> int:
    if not os.path.exists(OFFSET_FILE):
        return 0
    with open(OFFSET_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("offset", 0)


def _save_offset(offset: int):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OFFSET_FILE, "w", encoding="utf-8") as f:
        json.dump({"offset": offset}, f)


def _get_updates(offset: int) -> list[dict]:
    url = f"{API_BASE}/bot{TOKEN}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": 0}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", [])


def _format_offer_line(offer: dict) -> str:
    pct = offer.get("cashback_percent")
    pct_str = f" — {pct}%" if pct is not None else ""
    return f"• {offer.get('title')}{pct_str}"


def _cmd_help() -> str:
    return (
        "🤖 <b>ხელმისაწვდომი ბრძანებები:</b>\n"
        "/latest [N] — ბოლოს დამატებული N შეთავაზება (default 5)\n"
        "/top10 — ტოპ 10 შეთავაზება ქეშბექის მიხედვით\n"
        "/category &lt;სახელი&gt; — შეთავაზებები კატეგორიის მიხედვით\n"
        "/ending — მალე დასრულებადი შეთავაზებები\n"
        "/help — ეს შეტყობინება"
    )


def _cmd_latest(state: dict, n: int = 5) -> str:
    n = max(1, min(n, 30))  # sane bounds so nobody accidentally asks for /latest 99999
    offers = sorted(state.values(), key=lambda o: o.get("first_seen", ""), reverse=True)[:n]
    if not offers:
        return "შეთავაზებები ვერ მოიძებნა."
    lines = [f"🆕 <b>ბოლო {len(offers)} შეთავაზება:</b>"] + [_format_offer_line(o) for o in offers]
    return "\n".join(lines)


def _cmd_top10(state: dict) -> str:
    offers = [o for o in state.values() if o.get("cashback_percent") is not None]
    offers.sort(key=lambda o: o["cashback_percent"], reverse=True)
    offers = offers[:10]
    if not offers:
        return "ქეშბექის მონაცემები ვერ მოიძებნა."
    lines = ["💰 <b>ტოპ 10 ქეშბექით:</b>"] + [_format_offer_line(o) for o in offers]
    return "\n".join(lines)


def _cmd_category(state: dict, query: str) -> str:
    query = query.strip().lower()
    if not query:
        available = ", ".join(sorted(CATEGORY_KEYWORDS.keys()))
        return f"გთხოვთ მიუთითოთ კატეგორია, მაგ:\n{available}"
    matches = [o for o in state.values() if query in (o.get("category") or "").lower()]
    if not matches:
        return f"'{query}' კატეგორიაში შეთავაზება ვერ მოიძებნა."
    lines = [f"📂 <b>{query}:</b>"] + [_format_offer_line(o) for o in matches[:20]]
    if len(matches) > 20:
        lines.append(f"...და კიდევ {len(matches) - 20}")
    return "\n".join(lines)


def _cmd_ending(state: dict) -> str:
    offers = [
        o for o in state.values()
        if o.get("remaining_days") is not None and o["remaining_days"] <= ENDING_SOON_THRESHOLD
    ]
    offers.sort(key=lambda o: o["remaining_days"])
    if not offers:
        return "უახლოეს დღეებში არაფერი სრულდება."
    lines = ["⏳ <b>მალე სრულდება:</b>"]
    for o in offers:
        lines.append(f"• {o.get('title')} — დარჩენილია {o['remaining_days']} დღე")
    return "\n".join(lines)


def handle_command(text: str, state: dict) -> str:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower().split("@")[0]  # strip "@YourBotName" if present
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/help", "/start"):
        return _cmd_help()
    if command == "/latest":
        n = int(arg) if arg.isdigit() else 5
        return _cmd_latest(state, n)
    if command == "/top10":
        return _cmd_top10(state)
    if command == "/category":
        return _cmd_category(state, arg)
    if command == "/ending":
        return _cmd_ending(state)
    return "უცნობი ბრძანება. სცადეთ /help"


def main():
    if not TOKEN or not CHAT_ID:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set, skipping.")
        return

    offset = _load_offset()
    updates = _get_updates(offset)

    if not updates:
        print("No new updates.")
        _save_offset(offset)  # ensure the file exists even on the very first run
        return

    state = load_state()
    max_update_id = offset - 1

    for update in updates:
        update_id = update.get("update_id", 0)
        max_update_id = max(max_update_id, update_id)

        message = update.get("message") or {}
        chat = message.get("chat", {})
        text = message.get("text", "")

        # Security: only ever respond to your own configured chat, so a
        # stranger who somehow messages the bot can't get it to leak data
        # or make it spend your API calls.
        if str(chat.get("id")) != str(CHAT_ID):
            print(f"Ignoring message from unrecognized chat id {chat.get('id')}")
            continue
        if not text.startswith("/"):
            continue

        reply = handle_command(text, state)
        try:
            send_message(reply)
        except Exception as e:
            print(f"Failed to send reply: {e}")

    _save_offset(max_update_id + 1)
    print(f"Processed {len(updates)} update(s).")


if __name__ == "__main__":
    main()
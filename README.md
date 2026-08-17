# Offers Bot — free Telegram tracker for Bank card offers

Checks tbcbank.ge daily for new/expired offers, sends you a Telegram
message, and generates weekly/monthly reports with charts. Runs entirely
on free infrastructure (GitHub Actions + Telegram Bot API).

## 1. One-time setup

### Telegram bot (free, ~2 min)
1. Message **@BotFather** on Telegram -> `/newbot` -> follow the prompts.
   You'll get a token like `123456:ABC-DEF1234ghIkl...`.
2. Send any message to your new bot (so it's allowed to message you back).
3. In your browser, open:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   Find `"chat":{"id": 123456789, ...}` — that number is your chat ID.

### GitHub repo
1. Create a new **public** GitHub repo (public = fully free Actions minutes,
   no limit). Push this folder's contents to it.
2. Go to **Settings -> Secrets and variables -> Actions** and add two
   repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. That's it — `check_offers.yml` will run daily automatically, and
   `reports.yml` will run weekly/monthly.

### How scraping works — updated ✅
`scraper.py` no longer parses HTML. TBC's offers page loads its data
client-side from an internal JSON API, so we call that directly:
```
POST https://apigw.tbcbank.ge/api/v1/marketing/entries/offer
```
Pagination uses a 0-indexed `pageIndex` field in the JSON body
(confirmed by testing — `page` and `pageNumber` are silently ignored
by the API). This is more reliable than HTML scraping since it won't
break if TBC changes their frontend markup, and it returns richer
data (including full offer descriptions) in a single request.

The API-response mapping is tested against a real captured sample
response — see `test_parse.py`.

## 2. Running locally (optional, for testing)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
python main.py          # daily check
python reports.py weekly    # or "monthly"
```

The very first run will populate `data/offers.json` without sending
notifications (otherwise you'd get ~300 Telegram messages at once for
every currently-live offer). Every run after that only notifies about
what actually changed.

## 3. How categorization works

TBC doesn't expose a category tag per offer on the listing page — only
as filter checkboxes. `categorize.py` uses free keyword matching against
the offer's title/brand text to guess a category. It's a heuristic, not
ground truth. Edit `CATEGORY_KEYWORDS` in that file whenever you notice a
mis-categorized offer — over time it gets more accurate for TBC's actual
merchant list.

## 4. What each file does

| File | Purpose |
|---|---|
| `scraper.py` | Fetches offers directly from TBC's JSON API |
| `categorize.py` | Free keyword-based category guesser |
| `telegram_notify.py` | Sends Telegram messages/photos |
| `main.py` | Daily job: diff against saved state, notify, save |
| `reports.py` | Weekly/monthly charts + summary |
| `data/offers.json` | Current known offers (auto-managed) |
| `data/history.jsonl` | Daily snapshot log for trend charts |
| `.github/workflows/*.yml` | Free cron scheduling |

## 5. Ideas to extend later (all still free)

- Track price/discount % changes on existing offers, not just new/expired
- "Offers ending soon" daily digest (remaining_days <= 2)
- Per-merchant history ("McDonald's has run 4 offers this year")
- A `/latest` Telegram command using long-polling in a second workflow
- Export `data/history.jsonl` to a simple static HTML dashboard via
  GitHub Pages (also free)

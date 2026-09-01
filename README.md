Offers Bot — TBC Bank offer tracker
Competitive-intelligence tooling for Bank of Georgia. Scrapes TBC Bank's
public offers listing once a day, classifies every offer, tracks how their
campaigns change over time, and publishes a dashboard plus Telegram alerts.
Runs entirely on free infrastructure: GitHub Actions for scheduling, GitHub
Pages for the dashboard, Telegram Bot API for alerts.
Briefing: https://jinchara.github.io/Offers_Bot/briefing.html
Dashboard: https://jinchara.github.io/Offers_Bot/dashboard.html
Source: https://github.com/jinchara/Offers_Bot
---
⚠️ If your dashboard shows everything under "აქტიური" and 0 elsewhere
That is not a bug in the pages — it means the data is still the old
schema. Checked against the live repo: all 540 records have
`remaining_days` and none has `end_date`.
`computeStatus()` sees no end date and calls the offer "evergreen", which
is correct for a genuine standing offer but wrong for a whole file that
predates the field. Everything lands in აქტიური; მალე იწურება,
ჯერ არ დაწყებულა and დასრულებული are all empty.
Fix: push the Python and run the migration (below). The pages now
detect this and show a warning banner instead of failing quietly.
---
Upgrading from the previous version
Run this once, after pulling, before the next scheduled scrape:
```bash
pip install -r requirements.txt
python migrate_state.py    # upgrades data/offers.json to the new schema
python test_parse.py       # should print ALL 65 TESTS PASSED
git add data/ && git commit -m "Migrate offer data to status-aware schema" && git push
```
`migrate_state.py` is safe to re-run and doesn't call the network. Without
it the dashboard still loads, but every offer shows as open-ended until the
next scrape fills in real dates.
---
What was wrong, and what fixed it
1. Finished offers showed as "მალე იწურება" with 0 days left
The scraper computed `max((end_date - today).days, 0)` and then discarded
the raw dates. Three problems fell out of that one line:
A campaign that ended in November and one ending tonight both stored `0`.
The information needed to tell them apart was destroyed at scrape time.
`remaining_days` was a snapshot. If a scheduled run slipped by two days,
the site showed a countdown that was two days wrong.
Offers that hadn't started yet were counted as live. TBC publishes
these — their listing shows `დასაწყისი: 25 აგვისტო`.
Fix. `start_date` and `end_date` are persisted raw. Status is derived on
demand by `offer_status.py`, and again in the browser by `offers-core.js`,
so the countdown is right whenever someone opens the page rather than only
right after a scrape.
Five statuses now exist:
Status	Meaning	Counts as live?
`upcoming`	announced, hasn't started	no
`active`	running, more than 3 days left	yes
`ending_soon`	running, 3 or fewer days left (`0` = last day)	yes
`ended`	end date has passed	no
`evergreen`	no end date — a standing partner discount	yes
`evergreen` matters more than it sounds: 323 of your 541 offers have no
end date at all. They aren't expired and they aren't broken records —
they're permanent partner discounts (Columbia, Converse, Kerama Marazzi).
Treating them as "0 days left" or as bad data would both be wrong.
2. Analysis mixed live and finished offers
The rule now applied everywhere:
> **Snapshot metrics count live offers only. Period metrics count every
> offer that was running during the window, ended or not.**
So "average cashback TBC is offering" excludes the campaign that finished
in November, while "how many campaigns did TBC launch last month" obviously
includes it. The weekly report uses the first rule, the monthly report uses
the second, and each states which one it's using in the message.
Nothing is deleted to achieve this. Offers TBC drops from their listing are
kept with `still_listed: false` — previously they vanished from
`offers.json` entirely, which made "how many offers ran in July?"
unanswerable, because the July offers were gone.
3. მეტრომარტი was filed under ტრანსპორტი
The old categoriser did `if keyword in haystack` on a plain string and
returned on the first match, walking categories in dict order:
`"მეტრო"` is a transport keyword, and `"მეტრომარტში"` contains it. Same
bug put `"smart"` inside `"smartphone"` into სურსათი.
First-match-wins meant a stray `"ონლაინ"` anywhere in the copy beat every
more specific signal that happened to be checked later.
62% of offers (335/541) fell through to "სხვა".
Fix. Four layers, most trustworthy first:
`data/category_overrides.json` — manual corrections, always win
TBC's own category tags, when `scraper.py` can read them
A curated merchant dictionary (~330 brands from your actual data)
Weighted keyword scoring over tokens, not substrings, with veto rules
Every category is scored and the highest total wins. Patterns come in three
flavours, which is what fixes the Georgian-suffix problem:
```
"მეტრო"        exact token   — will NOT match მეტრომარტში
"მეტრომარტ*"   token prefix  — matches all its case endings
"auto service" phrase        — plain substring
```
Result: uncategorised dropped from 61.9% to 19.8%.
---
New in this version
`bank_product` flag. 49 records were branded `განაწილება`,
`განვადება`, `თიბისი` or `Mastercard` — TBC's own payment products, not
merchant partnerships. They were inflating every category share and every
average. They're now flagged and excluded from competitive metrics, while
still being tracked.
`channel` field. TBC folds online merchants into "ონლაინ პარტნიორები",
which throws away what the merchant sells — ოკაიდი.ჯი and ოკაიდი end up in
different categories despite being the same business. We keep the product
category and record the channel separately, so you can slice either way.
Campaign-shape analytics. The tactical read, and the thing hardest for
a competitor to copy from a screenshot:
Median campaign length: 7 days
41.4% of dated campaigns run 3 days or fewer — TBC runs flash
promotions, not standing offers
Launches by weekday, so you can see when they push
Category coverage gaps. The dashboard now lists categories where TBC
has zero or very few live offers. The empty rows are the interesting ones.
Rate movements. Partners whose cashback percentage changed between
scrapes, read off `cashback_history`. A merchant going 15% → 25% is worth a
Slack ping.
Data-quality panel. Categories are inferred, not published by TBC, so
the dashboard states what share was resolved, by which method, and lists
what's still unresolved. Nobody should present these charts to the squad
without that number visible.
---
The three pages
They answer different questions on purpose.
`briefing.html` — start here. Everything on it is a diff or a
decision, never a catalogue. If it duplicates something TBC's own site
shows, it doesn't belong on this page.
7-day movement: launched, ended, net
Signals, each stating why it's worth reading: aggressive cashback
(30%+), Concept-exclusive offers, flash campaigns, first-time partners
A 14-day calendar of starts and ends. This is the piece TBC cannot
give you — their site shows one offer's dates, never the shape of the
whole schedule. Seeing seven campaigns end on the same Sunday is what
lets you time a response instead of reacting to one.
Category pressure, ranked by depth × generosity, because 40 offers at 5%
and 4 offers at 40% are different competitive facts
A copy-ready text summary. The last mile of this tool is somebody
pasting it into Slack; a dashboard nobody can quote doesn't travel.
`dashboard.html` — the analytical layer. Distributions, trends, campaign
tactics, partner concentration, data quality.
`index.html` — the offer browser. You were right that it resembles TBC's
own page, and that's fine for what it's for: looking a specific merchant
up, checking one offer's terms, filtering by segment. It's a lookup tool,
not the deliverable. The briefing is the deliverable.
---
Files
File	Purpose
`scraper.py`	Fetches from TBC's JSON API; keeps raw dates; probes category facets
`offer_status.py`	Derives status from dates — the single source of truth
`categorize.py`	Four-layer categoriser, channel detection, cashback parsing
`ka_dates.py`	Parses Georgian date ranges out of offer copy
`analytics.py`	Builds `data/insights.json`
`main.py`	Daily job: fetch, diff, notify, persist
`reports.py`	Weekly/monthly Telegram reports with charts
`state_store.py`	Atomic reads/writes, archive retention
`migrate_state.py`	One-off upgrade of existing data
`telegram_commands.py`	`/latest`, `/top10`, `/category`, `/ending`
`offers-core.js`	Shared browser-side status logic
`index.html`	Offer browser
`dashboard.html`	Analytics dashboard
`tbc_taxonomy.py`	TBC's filter vocabulary — facets, slugs, segments
`briefing.html`	Daily briefing for the BOG team
`test_parse.py`	Regression suite (97 assertions)
Data files
File	Contents
`data/offers.json`	Every offer ever seen, keyed by slug
`data/history.jsonl`	One row per run, counts split by status
`data/insights.json`	Pre-computed analytics
`data/facet_map.json`	Resolved filter slugs (auto-generated, hand-editable)
`data/category_overrides.json`	Your manual corrections
---
Fixing a wrong category
Open the dashboard, scroll to მონაცემების ხარისხი at the bottom, and
look at the uncategorised list. Then add one line to
`data/category_overrides.json`:
```json
{
  "by_brand": {
    "მეტრომარტი": "ტექნიკა",
    "ახალი ბრენდი": "სახლი"
  }
}
```
Overrides beat every other rule, so this takes effect on the next run with
no code change. `by_brand` is preferred over `by_slug` — it covers every
offer that merchant ever runs, including future ones. Brand matching
ignores case and punctuation.
---
Running locally
```bash
pip install -r requirements.txt

python test_parse.py            # regression suite, no network needed
python analytics.py             # text summary of the current data
python scraper.py               # fetch and report a count, writes nothing

export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python main.py                  # full daily job
python reports.py weekly        # or monthly
```
Telegram is optional. With no token set, `main.py` writes all the data and
skips notifications, so it works fine as a pure pipeline.
To view the dashboard locally you need a web server, because browsers block
`fetch` from `file://`:
```bash
python -m http.server 8000      # then open http://localhost:8000
```
---
Exact categories, from TBC's own filters
Guessing categories from wording is now the fallback, not the plan.
Their listing URL encodes filter state like this:
```
?segment=All&page=1&filters=Category!Auto,Shopping$ProductType!TBCCard
                            $OfferType!Cashback$CardType!CreditCard,MasterCard
```
`$` separates facets, `!` separates a facet from its values, `,` separates
multiple values. The JSON API takes the same thing as a list — one string
per facet — which is why the original `["ProductType!TBCCard"]` worked.
So instead of inferring a category, we ask TBC "which offers are in
`Category!Auto`?" and tag whatever comes back. Their answer is
definitional, not an opinion.
Why the first attempt failed. The facet name `Category` was right, but
values are English PascalCase slugs, not the Georgian labels in the UI.
The probe sent `Category!ტექნიკა`, and an unrecognised value is silently
ignored by their API rather than rejected — so it returned the whole
catalogue. The probe correctly refused to trust a filter that didn't narrow
anything, which is why it reported failure instead of tagging all 541
offers as ტექნიკა.
`tbc_taxonomy.py` now holds all four facets with their Georgian labels,
English labels, and candidate slugs. Single-word labels are unambiguous;
multi-word ones ("Cafe and Restaurant", "Beauty & Health") carry several
candidates. `scraper.resolve_facet_values()` tries each against the live
API and keeps whichever returns a genuine subset, caching the result in
`data/facet_map.json`.
```bash
python scraper.py --discover
```
This resolves every slug and prints anything it couldn't. Unresolved values
are reported rather than guessed — a wrong slug and a genuinely empty
category look identical from outside, so neither gets assumed.
Each offer then stores TBC's own tags separately from our inferred
ones, so the two can never be confused:
Field	Source
`tbc_categories`	TBC's `Category` facet — authoritative
`product_types`	TBC's `ProductType` facet
`tbc_offer_types`	TBC's `OfferType` facet
`card_types`	TBC's `CardType` facet
`category`	single best category — uses the TBC tag when present
`category_source`	`api` when it came from TBC, else `brand` / `keywords`
Set `USE_TBC_CATEGORIES=0` to skip facet tagging entirely.
Cost: about 35 paginated requests once a day — a smaller footprint than a
person clicking through the listing by hand.
---
Segments: All / Concept / For Youth
Segment is a top-level query parameter, not a facet:
```
?segment=All  |  ?segment=Concept  |  ?segment=ForYouth
```
The three audiences overlap. Each offer records which ones it appears in,
plus a `concept_only` flag.
This distinction is the commercially interesting one. Concept is TBC's
premium tier, so an offer running only in Concept is a retention play
aimed at high-value customers, not a mass-acquisition push — and it calls
for a different response. Averaging it in with everything else hides that
completely.
The offer browser gains a segment switch, and the briefing lists
Concept-exclusive offers as their own signal.
---
How the scraping works
TBC's offers page is an Angular SPA that populates itself from an internal
JSON endpoint, so we call that directly rather than parsing HTML:
```
POST https://apigw.tbcbank.ge/api/v1/marketing/entries/offer
```
Pagination is 0-indexed via `pageIndex` (`page` and `pageNumber` are
silently ignored). This survives frontend redesigns and returns richer data
than the rendered page, including full descriptions.
This reads the same publicly available marketing pages any customer can
browse — no authentication, no personal data, one request cycle a day.
---
A note on the numbers
Two things to keep in mind before presenting this to anyone:
Categories are inferred. TBC doesn't publish a category per offer on
the listing, so ~20% currently sit in "სხვა" and some of the other 80% will
be wrong. The dashboard's data-quality panel tells you exactly how much is
inferred and by what method. Treat category splits as indicative.
Cashback and cap parsing is heuristic. It reads free-text Georgian
marketing copy. It handles the common phrasings and deliberately skips
percentages framed as interest rates, but a genuinely unusual sentence will
be parsed wrong. Spot-check anything you're going to quote.
"""
test_parse.py
Plain-assert regression suite. No pytest needed:

    python test_parse.py

Every test here corresponds to a bug that was actually in the data, so if
one of these fails, something real has regressed.
"""

# --- runtime guard (inlined) ----------------------------------------------
# NOT imported from a helper module on purpose: "console" is also a real
# package on PyPI, and if it happens to be installed it shadows a local
# console.py and every script dies with an ImportError. Six lines duplicated
# beats a name collision that only shows up on some machines.
#
# Python 3.10+ is required because the annotations use `date | None`, which
# is evaluated at import time. On 3.9 you'd get a bare TypeError from deep
# inside the imports instead of this message.
#
# stdout is forced to UTF-8 because on Windows it defaults to the system
# ANSI code page, which cannot encode Georgian — the first print of
# ქართული would otherwise raise UnicodeEncodeError after the network calls
# but before anything is saved.
import sys

if sys.version_info < (3, 10):
    sys.exit(
        "This project needs Python 3.10 or newer — you're on "
        + ".".join(str(n) for n in sys.version_info[:3])
    )

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
# ---------------------------------------------------------------------------

from datetime import date, timedelta

from categorize import (
    ELECTRONICS,
    OTHER,
    classify,
    detect_bank_product,
    detect_channel,
    extract_offer_economics,
    normalize_brand,
    score_categories,
)
from ka_dates import extract_date_range
from offer_status import compute_status, days_left_label, parse_api_date
from scraper import _absolutize_image, offer_from_api_item

TODAY = date(2026, 8, 23)
passed = 0


def check(condition, message):
    global passed
    assert condition, f"FAILED: {message}"
    passed += 1


def days_from_now(n):
    return (TODAY + timedelta(days=n)).isoformat() + "T23:59:00"


# =========================================================================
# 1. API mapping — the raw dates must survive
# =========================================================================
SAMPLE_ITEM = {
    "$id": "3NzwceYpvZVKz8TCsCsoWC",
    "description": "თიბისი კონცეპტის შეთავაზების ფარგლებში...",
    "title": "Kerama Marazzi",
    "startDate": "2026-08-06T00:00:00",
    "endDate": "2026-08-11T23:59:00",
    "slug": "qeshbeqi-kerama",
    "image": {"src": "//images.eu.ctfassets.net/psnuheg7hu1m/15Do/kerama.jpg"},
    "partner": {"title": "Kerama Marazzi", "slug": "kerama-marazzi"},
}

offer = offer_from_api_item(SAMPLE_ITEM)
check(offer["slug"] == "qeshbeqi-kerama", "slug mapped")
check(offer["url"] == "https://tbcbank.ge/ka/offers/all-offers/qeshbeqi-kerama", "url built")
check(offer["brand"] == "Kerama Marazzi", "partner title becomes brand")
check(offer["partner_slug"] == "kerama-marazzi", "partner slug kept")
check(offer["image"].startswith("https://"), "protocol-relative image absolutised")

# The whole point of the rewrite: dates are persisted, not thrown away.
check(offer["start_date"] == "2026-08-06T00:00:00", "start_date persisted")
check(offer["end_date"] == "2026-08-11T23:59:00", "end_date persisted")

# remaining_days may now be negative — that is what distinguishes an offer
# that ended from one ending today.
past = offer_from_api_item({"slug": "x", "endDate": days_from_now(-5)})
check(past["remaining_days"] < 0, "past offers report negative remaining_days, not 0")

check(_absolutize_image("//a.com/b.jpg") == "https://a.com/b.jpg", "image // prefix")
check(_absolutize_image("https://a.com/b.jpg") == "https://a.com/b.jpg", "absolute image untouched")
check(_absolutize_image(None) is None, "None image tolerated")

no_slug = offer_from_api_item({"title": "No Slug Offer"})
check(no_slug["slug"] is None and no_slug["url"] is None, "missing slug handled")

check(parse_api_date("2026-08-11T23:59:00Z") == date(2026, 8, 11), "Z suffix parsed")
check(parse_api_date("2026-08-11") == date(2026, 8, 11), "bare date parsed")
check(parse_api_date("not-a-date") is None, "garbage date returns None")
check(parse_api_date(None) is None, "None date returns None")


# =========================================================================
# 2. Status — the "0 days left but already finished" bug
# =========================================================================
ended = compute_status({"end_date": days_from_now(-20)}, TODAY)
check(ended["status"] == "ended", "past end date is ended")
check(ended["is_live"] is False, "ended offers are not live")

last_day = compute_status({"end_date": days_from_now(0)}, TODAY)
check(last_day["status"] == "ending_soon", "ends today is ending_soon, not ended")
check(last_day["is_live"] is True, "an offer ending today is still usable today")

# These two used to be indistinguishable. That was the reported bug.
check(ended["status"] != last_day["status"], "ended and ending-today are distinct statuses")

soon = compute_status({"end_date": days_from_now(2)}, TODAY)
check(soon["status"] == "ending_soon", "within threshold is ending_soon")

active = compute_status({"end_date": days_from_now(30)}, TODAY)
check(active["status"] == "active", "plenty of time left is active")

upcoming = compute_status(
    {"start_date": days_from_now(5), "end_date": days_from_now(15)}, TODAY
)
check(upcoming["status"] == "upcoming", "future start date is upcoming")
check(upcoming["is_live"] is False, "not-yet-started offers are not live")
check(upcoming["days_until_start"] == 5, "days_until_start computed")

evergreen = compute_status({"start_date": days_from_now(-100), "end_date": None}, TODAY)
check(evergreen["status"] == "evergreen", "no end date is evergreen")
check(evergreen["is_live"] is True, "evergreen offers count as live")

# An offer whose start has passed but whose end hasn't must never be upcoming.
started = compute_status(
    {"start_date": days_from_now(-1), "end_date": days_from_now(10)}, TODAY
)
check(started["status"] == "active", "started offers are active, not upcoming")

span = compute_status(
    {"start_date": days_from_now(-2), "end_date": days_from_now(2)}, TODAY
)
check(span["duration_days"] == 5, "duration is inclusive of both end days")

check(days_left_label(0) == "ბოლო დღე", "zero days reads as last day")
check(days_left_label(-3) == "დასრულებული", "negative days reads as finished")
check(days_left_label(None) == "ვადის გარეშე", "no end date has its own label")


# =========================================================================
# 3. Categorisation — the მეტრომარტი bug and its whole family
# =========================================================================
metromart = {
    "slug": "metromart-ganatsileba",
    "title": "დაიბრუნე 20%, მაქს. 200₾ მეტრომარტში",
    "brand": "მეტრომარტი",
    "description": "21-23 აგვისტოს, შეარჩიე ნივთი მეტრომარტის მაღაზიებში.",
}
result = classify(metromart)
check(result["category"] == ELECTRONICS, "მეტრომარტი is ტექნიკა, not ტრანსპორტი")
check(result["category_source"] == "brand", "resolved from the brand dictionary")

# The underlying cause: "მეტრო" must not match inside "მეტრომარტში".
scores = score_categories(metromart)
check("ტრანსპორტი" not in scores, "transport is vetoed for metromart text")

# Exact-token patterns must still match a real standalone word.
metro = {"title": "მეტრო სადგურებში ფასდაკლება", "brand": "", "description": ""}
check("ტრანსპორტი" in score_categories(metro), "standalone მეტრო still scores transport")

# Same class of collision: "smart" inside "smartphone".
phone = {"title": "Smartphone-ებზე ფასდაკლება", "brand": "", "description": ""}
check("სურსათი" not in score_categories(phone), "smartphone does not score as grocery")

# Scoring beats first-match-wins: the strongest signal should win even when
# a weaker category appears earlier in the rule dictionary.
restaurant = {
    "brand": "ვასაბი",
    "title": "სუში რესტორანში 20% ფასდაკლება",
    "description": "ონლაინ შეკვეთისას",
}
check(classify(restaurant)["category"] == "კაფე და რესტორანი",
      "restaurant beats a stray 'ონლაინ' mention")

unknown = {"slug": "z", "title": "შეთავაზება", "brand": "ზზზ უცნობი", "description": ""}
check(classify(unknown)["category"] == OTHER, "genuinely unknown stays სხვა")
check(classify(unknown)["category_confidence"] == "low", "unknown is flagged low confidence")

# API tags, when available, outrank our guesses.
tagged = classify(metromart, api_categories=["სახლი"])
check(tagged["category"] == "სახლი" and tagged["category_source"] == "api",
      "TBC's own tag wins over the brand dictionary")

check(normalize_brand("ჯეკ & ჯონსი") == "ჯეკ ჯონსი", "ampersand collapses to one space")
check(normalize_brand("Cosmo.com.ge") == "cosmo", ".com.ge stripped")
check(normalize_brand(None) == "", "None brand tolerated")

# .ჯი / .ge storefronts resolve to the same category as the physical shop.
check(classify({"brand": "მინილენდ.ჯი", "title": "", "description": ""})["category"]
      == classify({"brand": "მინილენდი", "title": "", "description": ""})["category"],
      "online and offline arms of a merchant agree")

check(detect_channel({"brand": "უკვე.ჯი"}) == "online", ".ჯი brand is an online channel")
check(detect_channel({"brand": "ზარა", "description": "მაღაზიებში"}) == "instore",
      "physical shop is instore")

check(detect_bank_product({"brand": "განაწილება"}) == "განაწილება", "bank product detected")
check(detect_bank_product({"brand": "ზარა"}) is None, "merchants are not bank products")


# =========================================================================
# 4. Economics parsing
# =========================================================================
econ = extract_offer_economics(
    {"title": "დაიბრუნე 20%, მაქს. 200₾ მეტრომარტში", "description": ""}
)
check(econ["cashback_percent"] == 20, "cashback percent read")
check(econ["cap_amount"] == 200.0, "cap amount read")
check(econ["cap_unlimited"] is False, "capped offer not marked unlimited")
check(econ["offer_type"] == "cashback", "offer type classified as cashback")

unlimited = extract_offer_economics(
    {"title": "დაიბრუნეთ 30% ულიმიტოდ", "description": ""}
)
check(unlimited["cap_unlimited"] is True, "unlimited cap detected")
check(unlimited["cap_amount"] is None, "unlimited offers carry no cap amount")

# An interest rate must not be mistaken for a customer benefit.
rate = extract_offer_economics(
    {"title": "0%-იანი განვადება", "description": "6-დან 12 თვემდე, ეფექტური 4.3%"}
)
check(rate["cashback_percent"] != 4, "effective interest rate is not read as cashback")
check(rate["offer_type"] == "installment", "instalment offer typed correctly")


# =========================================================================
# 5. Georgian date extraction
# =========================================================================
ref = date(2026, 8, 20)
check(extract_date_range("21-23 აგვისტოს, შეარჩიე", ref) == (date(2026, 8, 21), date(2026, 8, 23)),
      "same-month day range")
check(extract_date_range("13 აგვისტოდან 13 ნოემბრის ჩათვლით", ref)
      == (date(2026, 8, 13), date(2026, 11, 13)), "cross-month range")
check(extract_date_range("27 ნოემბერს, გადაიხადე", date(2026, 11, 20))
      == (date(2026, 11, 27), date(2026, 11, 27)), "single day")
check(extract_date_range("2026 წლის 24 ივნისის 15:00 საათიდან", date(2026, 6, 1))[0]
      == date(2026, 6, 24), "explicit year respected")
check(extract_date_range("ფასდაკლება ყველა პროდუქტზე", ref) == (None, None),
      "no date in text returns None rather than guessing")

# max_date is what lets migration resolve "15 ნოემბერს" to LAST November.
bounded = extract_date_range("15-16 ნოემბერს", date(2026, 8, 17), max_date=date(2026, 8, 23))
check(bounded[1] == date(2025, 11, 16), "max_date forces the year into the past")

# Nonsense dates must not crash or produce a bogus result.
check(extract_date_range("45 აგვისტოს", ref) == (None, None), "impossible day rejected")


# =========================================================================
# 6. TBC filter taxonomy
# =========================================================================
from tbc_taxonomy import (
    CATEGORIES,
    FACETS,
    SEGMENT_KEYS,
    build_ka_lookup,
    derive_slug,
)

check(len(CATEGORIES) == 19, "all 19 TBC categories are listed")
check(SEGMENT_KEYS == ["All", "Concept", "ForYouth"], "three audience segments")

# Slugs confirmed from a real filtered URL supplied by TBC's own site:
# filters=Category!Auto,Shopping$ProductType!TBCCard$OfferType!Cashback
#         $CardType!CreditCard,MasterCard
slug_for = {ka: candidates[0] for ka, _en, candidates in CATEGORIES}
check(slug_for["ავტო"] == "Auto", "ავტო resolves to the confirmed slug Auto")
check(slug_for["შოპინგი"] == "Shopping", "შოპინგი resolves to the confirmed slug Shopping")
check(FACETS["ProductType"][0][2][0] == "TBCCard", "TBCCard slug confirmed")
check("Cashback" in [c[0] for _ka, _en, c in FACETS["OfferType"]], "Cashback slug confirmed")
check("MasterCard" in [c[0] for _ka, _en, c in FACETS["CardType"]], "MasterCard slug confirmed")

# Every Georgian category in the taxonomy must exist in categorize.py, or
# an API tag would introduce a category the dashboard has never heard of.
from categorize import TBC_CATEGORIES as CATEGORIZER_CATEGORIES
for ka, _en, _c in CATEGORIES:
    check(ka in CATEGORIZER_CATEGORIES, f"categorizer knows the category {ka}")

# The slug rule, recovered from two captured requests: capitalise each
# word of the English label, delete the spaces, keep punctuation as-is.
# These are the real slugs the live API answered to.
_slug_rule = [
    ("Cafe and Restaurant", "CafeAndRestaurant"),
    ("Online Partners", "OnlinePartners"),
    ("Beauty & Health", "Beauty&Health"),      # ampersand survives
    ("Pupil's Card", "Pupil'sCard"),           # apostrophe survives
    ("For Kids", "ForKids"),
    ("TBC Concept Card", "TBCConceptCard"),
    ("Credit Card", "CreditCard"),
    ("Partner Offers", "PartnerOffers"),
    ("Shopping", "Shopping"),
    ("MasterCard", "MasterCard"),
]
for _label, _want in _slug_rule:
    check(derive_slug(_label) == _want, f"derive_slug({_label!r}) == {_want!r}")

# Every vocabulary entry must end up able to try the derived form, so a
# category TBC adds later resolves without anyone editing the file.
for _facet, _vocab in FACETS.items():
    for _ka, _en, _candidates in _vocab:
        check(derive_slug(_en) in _candidates,
              f"{_facet}.{_en} can try its derived slug")

# The reverse lookup must survive the resolver picking a non-first
# candidate. Derive the canonical slug rather than hard-coding it — the
# candidate order changes as slugs get confirmed, and a test that breaks
# every time the list is reordered is a test nobody trusts.
_health_ka = "ჯანმრთელობა და სილამაზე"
_health_canonical = next(c[0] for ka, _en, c in CATEGORIES if ka == _health_ka)
lookup = build_ka_lookup({"Category": {_health_canonical: "SomeOtherSpelling"}})
check(lookup["Category"]["SomeOtherSpelling"] == _health_ka,
      "ka labels follow whichever slug the API actually accepted")
check(lookup["Category"]["Auto"] == "ავტო", "unresolved values fall back to canonical slug")

# Confirmed against the live API — these must not drift.
_confirmed = {
    "ავტო": "Auto", "შოპინგი": "Shopping", "ტრანსპორტი": "Transport",
    "ტანსაცმელი": "Clothes", "კაფე და რესტორანი": "CafeAndRestaurant",
    "საბავშვო": "ForKids", "ონლაინ პარტნიორები": "OnlinePartners",
    "ტექნიკა": "Electronics", "სურსათი": "Groceries", "მოგზაურობა": "Travel",
    # The two that took longest. Both were failing because every guess
    # sanitised the punctuation away; TBC keeps it verbatim.
    "ჯანმრთელობა და სილამაზე": "Beauty&Health",
}
for _ka, _slug in _confirmed.items():
    _first = next(c[0] for ka, _en, c in CATEGORIES if ka == _ka)
    check(_first == _slug, f"{_ka} resolves to the confirmed slug {_slug}")


# =========================================================================
# 7. Filter payload — pinned to a real captured request
# =========================================================================
# Captured from the site's own POST when the ტრანსპორტი checkbox is ticked:
#   {"filter":["Category:Transport"],"locale":"ka-GE","segment":"All",
#    "pageIndex":0,"pageSize":12}
# Two details are easy to get wrong and were, for several rounds: the key
# is `filter` singular (the plural is accepted and silently ignored), and
# the separator is a colon even though the URL bar shows `!`.
from unittest.mock import patch

import scraper as _scraper

check(_scraper.FILTER_KEY == "filter", "payload key is `filter`, not `filters`")
check(_scraper.FILTER_SEPARATOR == ":", "facet separator is a colon, not `!`")
check(_scraper.make_filter("Category", "Transport") == "Category:Transport",
      "single-value filter term")
check(_scraper.make_filter("Category", "Auto", "Shopping") == "Category:Auto,Shopping",
      "multi-value terms are comma-joined")
check(_scraper.DEFAULT_FILTERS == [],
      "default filter is empty — a non-empty one would silently scrape a subset")


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"pagingDetails": {"totalCount": 0, "totalPages": 1,
                                  "isLastPage": True}, "list": []}


_sent = {}


def _fake_post(url, json=None, headers=None, timeout=None):
    _sent["url"] = url
    _sent["body"] = json
    return _FakeResp()


with patch.object(_scraper.requests, "post", _fake_post):
    _scraper.fetch_offers_page(
        0, "All", filters=[_scraper.make_filter("Category", "Transport")], page_size=12
    )

check(_sent["url"] == "https://apigw.tbcbank.ge/api/v1/marketing/entries/offer",
      "endpoint unchanged")
check(_sent["body"] == {
    "filter": ["Category:Transport"],
    "locale": "ka-GE",
    "segment": "All",
    "pageIndex": 0,
    "pageSize": 12,
}, "outgoing payload matches the captured browser request exactly")

with patch.object(_scraper.requests, "post", _fake_post):
    _scraper.fetch_offers_page(0)
check(_sent["body"]["filter"] == [], "unfiltered fetch sends an empty filter list")


print(f"\nALL {passed} TESTS PASSED")
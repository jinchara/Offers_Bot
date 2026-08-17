from datetime import date, timedelta

from scraper import offer_from_api_item, _absolutize_image, _remaining_days

# Real sample item captured from TBC's actual API response
# (POST https://apigw.tbcbank.ge/api/v1/marketing/entries/offer)
SAMPLE_ITEM = {
    "$id": "3NzwceYpvZVKz8TCsCsoWC",
    "description": "თიბისი კონცეპტის შეთავაზების ფარგლებში...",
    "title": "Kerama Marazzi",
    "startDate": "2026-08-06T00:00:00",
    "endDate": "2026-08-11T23:59:00",
    "slug": "qeshbeqi-kerama",
    "image": {
        "src": "//images.eu.ctfassets.net/psnuheg7hu1m/15DoPsX7UWzvhJLzQqXO3f/fe7d528abd39bd4f2664cb895f8a0114/kerama.jpg"
    },
    "partner": {
        "title": "Kerama Marazzi",
        "slug": "kerama-marazzi",
    },
}

offer = offer_from_api_item(SAMPLE_ITEM)
print("MAPPED OFFER:", offer)

assert offer["slug"] == "qeshbeqi-kerama"
assert offer["url"] == "https://tbcbank.ge/ka/offers/all-offers/qeshbeqi-kerama"
assert offer["title"] == "Kerama Marazzi"
assert offer["brand"] == "Kerama Marazzi"
assert offer["image"] == "https://images.eu.ctfassets.net/psnuheg7hu1m/15DoPsX7UWzvhJLzQqXO3f/fe7d528abd39bd4f2664cb895f8a0114/kerama.jpg"
assert "description" in offer

# --- image URL handling ---
assert _absolutize_image("//images.eu.foo/bar.jpg") == "https://images.eu.foo/bar.jpg"
assert _absolutize_image("https://already-absolute.com/x.jpg") == "https://already-absolute.com/x.jpg"
assert _absolutize_image(None) is None

# --- remaining_days handling ---
future = (date.today() + timedelta(days=5)).isoformat() + "T23:59:00"
assert _remaining_days(future) == 5

past = (date.today() - timedelta(days=3)).isoformat() + "T23:59:00"
assert _remaining_days(past) == 0  # clamped, never negative

assert _remaining_days(None) is None
assert _remaining_days("not-a-date") is None

# --- missing slug is handled gracefully ---
no_slug = offer_from_api_item({"title": "No Slug Offer"})
assert no_slug["slug"] is None
assert no_slug["url"] is None

print("\nALL TESTS PASSED")
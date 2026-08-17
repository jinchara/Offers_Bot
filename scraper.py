"""
scraper.py
Fetches TBC Bank's offers directly from their internal JSON API instead of
scraping rendered HTML. TBC's offers page is an Angular SPA that populates
itself by calling this endpoint client-side, so hitting it directly is more
reliable than parsing HTML (no CSS class guessing, and it survives frontend
redesigns).

Endpoint discovered via DevTools / by inspecting the site's JS bundles:
    POST https://apigw.tbcbank.ge/api/v1/marketing/entries/offer

Pagination is 0-indexed via the `pageIndex` field in the JSON body (NOT
`page` or `pageNumber` — both are silently ignored by the API).
"""

import json
from datetime import date, datetime
from urllib import error, request

try:
    import requests  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback for minimal environments
    requests = None

BASE_URL = "https://tbcbank.ge"
API_URL = "https://apigw.tbcbank.ge/api/v1/marketing/entries/offer"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://tbcbank.ge",
    "Referer": "https://tbcbank.ge/ka/offers/all-offers",
}
PAGE_SIZE = 12


def _absolutize_image(src):
    """TBC returns protocol-relative image URLs like '//images.eu...'."""
    if not src:
        return None
    if src.startswith("//"):
        return f"https:{src}"
    return src


def _remaining_days(end_date_str):
    if not end_date_str:
        return None
    try:
        end = datetime.fromisoformat(end_date_str).date()
    except ValueError:
        return None
    return max((end - date.today()).days, 0)


def offer_from_api_item(item: dict) -> dict:
    """
    Maps one raw item from the API's `list` array into our internal offer
    shape: {slug, url, title, brand, image, remaining_days, description}
    """
    slug = item.get("slug")
    partner = item.get("partner") or {}
    image = item.get("image") or {}

    return {
        "slug": slug,
        "url": f"{BASE_URL}/ka/offers/all-offers/{slug}" if slug else None,
        "title": item.get("title"),
        "brand": partner.get("title"),
        "image": _absolutize_image(image.get("src")),
        "remaining_days": _remaining_days(item.get("endDate")),
        "description": item.get("description"),
    }


def fetch_offers_page(
    page_index: int,
    segment: str = "All",
    filters: list | None = None,
    page_size: int = PAGE_SIZE,
) -> dict:
    """Fetches one raw page of results straight from the API."""
    payload = {
        "locale": "ka-GE",
        "segment": segment,
        "filters": filters or ["ProductType!TBCCard"],
        "pageSize": page_size,
        "pageIndex": page_index,
    }
    resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_all_offers(segment: str = "All", filters: list | None = None) -> list[dict]:
    """
    Fetches every offer across all pages, deduplicated by slug, mapped to
    our internal offer shape.
    """
    filters = filters or ["ProductType!TBCCard"]

    first = fetch_offers_page(0, segment, filters)
    total_pages = first.get("pagingDetails", {}).get("totalPages", 1)

    all_offers = [offer_from_api_item(o) for o in first.get("list", [])]
    seen_slugs = {o["slug"] for o in all_offers if o["slug"]}

    for page_index in range(1, total_pages):
        page = fetch_offers_page(page_index, segment, filters)
        for item in page.get("list", []):
            offer = offer_from_api_item(item)
            if offer["slug"] and offer["slug"] not in seen_slugs:
                all_offers.append(offer)
                seen_slugs.add(offer["slug"])

    return all_offers


def fetch_offer_detail(slug: str) -> dict:
    """
    Kept for backwards compatibility with any code that wants a single
    offer's full detail. Since the listing API already includes a full
    `description`, this just re-fetches that offer's page and finds it —
    it's a convenience wrapper, not a second data source.
    """
    for page_index in range(0, 1000):
        page = fetch_offers_page(page_index)
        for item in page.get("list", []):
            if item.get("slug") == slug:
                return offer_from_api_item(item)
        paging = page.get("pagingDetails", {})
        if paging.get("isLastPage", True):
            break
    raise ValueError(f"Offer with slug '{slug}' not found")
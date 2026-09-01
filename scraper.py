"""
scraper.py
Reads TBC Bank's offers from their internal JSON API rather than scraping
rendered HTML. The offers page is an Angular SPA that populates itself from
this endpoint, so calling it directly is both more reliable and richer.

    POST https://apigw.tbcbank.ge/api/v1/marketing/entries/offer

Pagination is 0-indexed via `pageIndex` (`page` and `pageNumber` are
silently ignored).

WHAT CHANGED IN THIS VERSION
----------------------------
1. `startDate` and `endDate` are now persisted raw. The old code threw them
   away and kept only `max(days_remaining, 0)`, which made an offer that
   ended in November indistinguishable from one ending tonight, and went
   stale the moment a scheduled run was skipped. Status is now derived on
   demand — see offer_status.py.

2. Category discovery. TBC's filter panel implies the API can filter by
   category, which would give us their own tags instead of our guesses.
   `discover_category_filters()` probes the facet naming at runtime and
   `fetch_category_map()` builds slug -> [category] from it. If the probe
   fails — different facet name, endpoint change, whatever — everything
   falls back to categorize.py's heuristics and the run still succeeds.
   Nothing here is load-bearing.

Run `python scraper.py --discover` to print the raw response shape and see
exactly which filter spellings the API accepts.
"""

import json
import os
import sys
from datetime import date, datetime

import requests

from tbc_taxonomy import FACETS, SEGMENT_KEYS, build_ka_lookup

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
PAGE_SIZE = 48          # fewer round trips than the site's own 12
REQUEST_TIMEOUT = 25

# The filter the site sends by default. Kept for parity with what a real
# browser session sends; it does not appear to narrow the result set.
DEFAULT_FILTERS = ["ProductType!TBCCard"]



def _absolutize_image(src):
    """TBC returns protocol-relative image URLs like '//images.eu...'."""
    if not src:
        return None
    if src.startswith("//"):
        return f"https:{src}"
    return src


def _iso_or_none(value):
    """Keeps the API's date string as-is if it parses, else None."""
    if not value:
        return None
    text = str(value).strip()
    try:
        datetime.fromisoformat(text.replace("Z", ""))
        return text
    except ValueError:
        return None


def offer_from_api_item(item: dict) -> dict:
    """
    Maps one raw item from the API's `list` array into our internal shape.

    `remaining_days` is still emitted so older consumers keep working, but
    it is a convenience only — always prefer computing status from
    start_date / end_date, which are the values actually persisted.
    """
    slug = item.get("slug")
    partner = item.get("partner") or {}
    image = item.get("image") or {}

    start_date = _iso_or_none(item.get("startDate"))
    end_date = _iso_or_none(item.get("endDate"))

    remaining_days = None
    if end_date:
        try:
            end = datetime.fromisoformat(end_date.replace("Z", "")).date()
            remaining_days = (end - date.today()).days
        except ValueError:
            remaining_days = None

    return {
        "slug": slug,
        "url": f"{BASE_URL}/ka/offers/all-offers/{slug}" if slug else None,
        "title": item.get("title"),
        "brand": partner.get("title"),
        "partner_slug": partner.get("slug"),
        "image": _absolutize_image(image.get("src")),
        "start_date": start_date,
        "end_date": end_date,
        # NOTE: can be negative. Negative means the offer already ended.
        "remaining_days": remaining_days,
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
        "filters": DEFAULT_FILTERS if filters is None else filters,
        "pageSize": page_size,
        "pageIndex": page_index,
    }
    resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _paginate(segment: str, filters: list | None, page_size: int = PAGE_SIZE):
    """Yields every raw item across all pages, guarding against runaway loops."""
    first = fetch_offers_page(0, segment, filters, page_size)
    paging = first.get("pagingDetails", {}) or {}
    total_pages = paging.get("totalPages") or 1

    yield from first.get("list", [])

    # Hard ceiling: even a full catalogue is well under 100 pages at this
    # page size. If the API ever reports something absurd, stop early
    # rather than hammering it.
    for page_index in range(1, min(total_pages, 100)):
        page = fetch_offers_page(page_index, segment, filters, page_size)
        yield from page.get("list", [])
        if (page.get("pagingDetails") or {}).get("isLastPage"):
            break


def fetch_all_offers(segment: str = "All", filters: list | None = None) -> list[dict]:
    """Every offer, deduplicated by slug, in our internal shape."""
    offers, seen = [], set()
    for item in _paginate(segment, filters):
        offer = offer_from_api_item(item)
        if offer["slug"] and offer["slug"] not in seen:
            offers.append(offer)
            seen.add(offer["slug"])
    return offers


# =========================================================================
# Facet resolution — turning TBC's filters into ground-truth tags
# =========================================================================
# The category problem is solved properly here. Instead of guessing a
# category from an offer's wording, we ask TBC's API "which offers are in
# Category!Auto?" and tag whatever comes back. Their answer is definitional.
#
# The only unknown is the exact spelling of each slug (see tbc_taxonomy).
# resolve_facet_values() settles that once and caches the result.

FACET_MAP_FILE = os.path.join(os.path.dirname(__file__), "data", "facet_map.json")


def _total_count(response: dict) -> int:
    paging = response.get("pagingDetails") or {}
    for key in ("totalCount", "totalItems", "total", "count"):
        if paging.get(key) is not None:
            return paging[key]
    pages = paging.get("totalPages")
    if pages is not None:
        return pages * PAGE_SIZE          # coarse, but enough to compare
    return len(response.get("list", []))


def catalogue_size(segment: str = "All") -> int:
    """Total offers with no facet filter applied — the comparison baseline."""
    return _total_count(fetch_offers_page(0, segment, filters=[], page_size=1))


def _try_filter(facet: str, slug: str, segment: str = "All"):
    """
    Count for one facet/value, or None if the API errored.

    Returns the raw count so the caller can decide whether it looks like a
    genuine subset.
    """
    try:
        resp = fetch_offers_page(0, segment, filters=[f"{facet}!{slug}"], page_size=1)
    except requests.RequestException:
        return None
    return _total_count(resp)


def resolve_facet_values(verbose: bool = True, use_cache: bool = True) -> dict:
    """
    Works out which slug spelling the API actually accepts for each value.

    Returns {facet: {canonical_slug: working_slug}}. A candidate is accepted
    only when it returns a STRICT SUBSET of the catalogue. This matters more
    than it looks: an unrecognised facet value is silently ignored by TBC's
    API, which then returns everything. Accepting that would tag all ~540
    offers with whichever category we happened to probe first — far worse
    than not resolving it at all.

    A value legitimately resolving to zero offers (an empty category) is
    indistinguishable from a wrong slug, so those stay unresolved and get
    reported rather than guessed at.
    """
    if use_cache and os.path.exists(FACET_MAP_FILE):
        try:
            with open(FACET_MAP_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("resolved"):
                if verbose:
                    print(f"Using cached facet map from {FACET_MAP_FILE} "
                          f"(delete it to re-probe).")
                return cached["resolved"]
        except (json.JSONDecodeError, OSError):
            pass

    baseline = catalogue_size()
    if not baseline:
        if verbose:
            print("Could not read a baseline catalogue size — skipping resolution.")
        return {}
    if verbose:
        print(f"Catalogue baseline: {baseline} offers\n")

    resolved, unresolved = {}, []
    for facet, vocabulary in FACETS.items():
        resolved[facet] = {}
        if verbose:
            print(f"--- {facet} ---")
        for ka, en, candidates in vocabulary:
            canonical = candidates[0]
            for slug in candidates:
                count = _try_filter(facet, slug)
                if count is not None and 0 < count < baseline:
                    resolved[facet][canonical] = slug
                    if verbose:
                        note = "" if slug == canonical else f"  (matched '{slug}')"
                        print(f"  ✓ {en:<22} {count:>4} offers{note}")
                    break
            else:
                unresolved.append((facet, en, candidates))
                if verbose:
                    print(f"  ✗ {en:<22} none of {candidates} returned a subset")

    if verbose and unresolved:
        print("\nUnresolved values — either the category is empty or the slug "
              "differs from every candidate:")
        for facet, en, candidates in unresolved:
            print(f"  {facet}.{en}: tried {candidates}")
        print(f"\nAdd the correct spelling to tbc_taxonomy.py, or edit "
              f"{FACET_MAP_FILE} directly.")

    payload = {
        "resolved": resolved,
        "baseline": baseline,
        "unresolved": [{"facet": f, "label": e, "tried": c} for f, e, c in unresolved],
    }
    os.makedirs(os.path.dirname(FACET_MAP_FILE), exist_ok=True)
    with open(FACET_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"\nSaved to {FACET_MAP_FILE}")
    return resolved


def fetch_facet_tags(resolved: dict, segment: str = "All",
                     verbose: bool = True) -> dict[str, dict[str, list[str]]]:
    """
    Builds {slug: {facet: [georgian labels]}} by querying every resolved
    facet value once.

    An offer can hold several values per facet — a card offer valid on both
    Visa and MasterCard appears under both — so values accumulate into
    lists rather than overwriting.

    Roughly 30 paginated queries in total, once a day. That is a smaller
    footprint than the page-by-page browse a person doing this manually
    would generate.
    """
    ka_lookup = build_ka_lookup(resolved)
    tags: dict[str, dict[str, list[str]]] = {}

    for facet, mapping in resolved.items():
        for canonical, working in mapping.items():
            label = ka_lookup[facet].get(working, working)
            try:
                items = list(_paginate(segment, [f"{facet}!{working}"]))
            except requests.RequestException as e:
                if verbose:
                    print(f"  {facet}.{label}: request failed ({e}) — skipped")
                continue
            for item in items:
                slug = item.get("slug")
                if not slug:
                    continue
                bucket = tags.setdefault(slug, {})
                bucket.setdefault(facet, [])
                if label not in bucket[facet]:
                    bucket[facet].append(label)
            if verbose:
                print(f"  {facet}.{label}: {len(items)}")
    return tags


def fetch_segment_membership(verbose: bool = True) -> dict[str, list[str]]:
    """
    Returns {slug: [segment keys]}.

    Segment is a top-level query parameter, not a facet, and the three
    audiences overlap — most offers are in All, a subset also appears under
    Concept or ForYouth. Knowing which is which is the difference between
    "TBC is offering 20% cashback" and "TBC is offering 20% cashback only
    to its premium tier".
    """
    membership: dict[str, list[str]] = {}
    for segment in SEGMENT_KEYS:
        try:
            items = list(_paginate(segment, DEFAULT_FILTERS))
        except requests.RequestException as e:
            if verbose:
                print(f"  segment {segment}: request failed ({e}) — skipped")
            continue
        for item in items:
            slug = item.get("slug")
            if slug:
                membership.setdefault(slug, []).append(segment)
        if verbose:
            print(f"  segment {segment}: {len(items)}")
    return membership


# =========================================================================
# Diagnostics
# =========================================================================

def _discover():
    """Prints the raw API shape and resolves every filter slug."""
    resp = fetch_offers_page(0, page_size=2)
    print("Top-level keys:", list(resp.keys()))
    print("\npagingDetails:", json.dumps(resp.get("pagingDetails"), ensure_ascii=False, indent=2))

    # If the response carries the filter vocabulary itself, that beats
    # probing — print it so the taxonomy can be corrected by hand.
    for key in ("facets", "filters", "aggregations", "categories", "filterOptions"):
        if key in resp:
            print(f"\n{key}:")
            print(json.dumps(resp[key], ensure_ascii=False, indent=2)[:3000])

    items = resp.get("list", [])
    if items:
        print("\nFirst item, full:")
        print(json.dumps(items[0], ensure_ascii=False, indent=2)[:2500])

    print("\n" + "=" * 60)
    print("Resolving filter slugs against the live API")
    print("=" * 60)
    resolve_facet_values(use_cache=False)

    print("\n" + "=" * 60)
    print("Segment sizes")
    print("=" * 60)
    for segment in SEGMENT_KEYS:
        try:
            print(f"  {segment}: {catalogue_size(segment)}")
        except requests.RequestException as e:
            print(f"  {segment}: failed ({e})")


if __name__ == "__main__":
    if "--discover" in sys.argv:
        _discover()
    else:
        found = fetch_all_offers()
        print(f"{len(found)} offers fetched.")
        dated = sum(1 for o in found if o["end_date"])
        print(f"{dated} carry an end date, {len(found) - dated} are open-ended.")

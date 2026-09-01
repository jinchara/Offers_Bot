"""
html_categories.py
Ground-truth categories, scraped from TBC's rendered listing.

    python html_categories.py            # resolve slugs + build the map
    python html_categories.py --debug    # dump what the parser sees

WHY NOT THE JSON API
--------------------
`filter_probe.py` showed eight payload shapes, three categories, every one
returning the full 514. Shape C (key renamed to `filter`) returned HTTP 400
— but note that shape also *omitted* `filters`, so the honest reading is
"`filters` is required but its contents are ignored", not "the server
validates values". Either way, no payload we can construct narrows the
result. Filtering is not available on that endpoint.

The site filters while rendering the page instead:

    https://tbcbank.ge/ka/offers/all-offers?segment=All&page=1&filters=Category!Auto

A plain requests.get of that URL returns only the ~9 KB Angular shell — no
offers, no filter state. Yet the same URL fetched through a JS-executing
client returns fully rendered HTML with the offer links present. So content
is either rendered client-side only, or prerendered for certain clients.

`--probe-render` tests that: same URL, different User-Agents and hosts,
reporting which combination returns real offer links. Many Angular sites
route crawler user-agents to a prerender service; if TBC does, one header
change makes this whole approach work.

WHAT THIS WRITES
----------------
data/category_map.json — {offer_slug: [georgian category, ...]}
categorize.py reads it above the brand dictionary and below manual
overrides, so exact tags win over inference but you can still correct
anything by hand.

COST
----
12 offers per page, ~19 categories, so roughly 60-80 GETs once a day. That
is less traffic than a person clicking through the same filters manually.
A small delay between requests keeps it polite.
"""

# --- runtime guard (inlined) ----------------------------------------------
# Deliberately not a shared module: "console" is a real PyPI package and
# shadows a local console.py wherever it happens to be installed.
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

import json
import os
import re
import time

import requests

from tbc_taxonomy import CATEGORIES, SEGMENTS

LISTING_URL = "https://tbcbank.ge/ka/offers/all-offers"
CATEGORY_MAP_FILE = os.path.join(os.path.dirname(__file__), "data", "category_map.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ka-GE,ka;q=0.9",
}

REQUEST_TIMEOUT = 30
DELAY_SECONDS = 0.4      # be a considerate guest
MAX_PAGES = 60           # hard stop; the unfiltered listing is ~46 pages

# Offer detail links look like /ka/offers/all-offers/<slug>. The trailing
# segment is required, which conveniently excludes the breadcrumb link back
# to the listing itself. Some slugs carry a Contentful id first
# (/all-offers/4has59ET6Awa0evY2VTFX8/summer-offer), so the last segment
# wins.
_OFFER_LINK_RE = re.compile(
    r'href="(?:https://tbcbank\.ge)?/(?:ka|en)/offers/all-offers/([A-Za-z0-9][A-Za-z0-9\-_/]*)"'
)

# TBC's "no results" copy. Presence of this means the filter was applied
# and matched nothing — different from a page that failed to render.
_NO_RESULTS = "შეთავაზებები არ მოიძებნა"


def fetch_listing(page: int = 1, filters: str | None = None,
                  segment: str = "All") -> str:
    params = {"segment": segment, "page": page}
    if filters:
        params["filters"] = filters
    resp = requests.get(LISTING_URL, params=params, headers=HEADERS,
                        timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def extract_offer_slugs(html: str) -> list[str]:
    """Offer slugs on one rendered page, order preserved, de-duplicated."""
    found, seen = [], set()
    for raw in _OFFER_LINK_RE.findall(html):
        slug = raw.rstrip("/").split("/")[-1]
        if slug and slug not in seen:
            found.append(slug)
            seen.add(slug)
    return found


def collect_all_slugs(filters: str | None = None, segment: str = "All",
                      verbose: bool = False) -> list[str]:
    """
    Walks every page of a filtered listing.

    Stops when a page yields nothing new. Comparing against slugs already
    collected — rather than trusting a page count parsed out of the
    pagination widget — means an out-of-range page that silently re-serves
    page 1 terminates the loop instead of looping forever.
    """
    collected, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        try:
            html = fetch_listing(page, filters, segment)
        except requests.RequestException as e:
            if verbose:
                print(f"    page {page} failed: {e}")
            break

        slugs = extract_offer_slugs(html)
        fresh = [s for s in slugs if s not in seen]
        if not fresh:
            break
        for s in fresh:
            collected.append(s)
            seen.add(s)
        if verbose:
            print(f"    page {page}: +{len(fresh)}")
        if len(slugs) < 12:      # a short page is the last page
            break
        time.sleep(DELAY_SECONDS)
    return collected


def resolve_category_slugs(baseline_total: int, verbose: bool = True) -> dict:
    """
    Finds which English slug spelling each category answers to.

    Accepts a candidate only when page 1 returns offers AND the full walk
    returns fewer than the whole catalogue. An unrecognised value makes the
    site fall back to showing everything, so "returned something" on its own
    is not evidence the filter worked.
    """
    resolved, unresolved = {}, []
    for ka, en, candidates in CATEGORIES:
        hit = None
        for slug in candidates:
            try:
                html = fetch_listing(1, f"Category!{slug}")
            except requests.RequestException as e:
                if verbose:
                    print(f"  {en:<22} request failed: {e}")
                continue
            time.sleep(DELAY_SECONDS)

            page_slugs = extract_offer_slugs(html)
            if _NO_RESULTS in html and not page_slugs:
                continue                       # recognised but empty, or wrong slug
            if not page_slugs:
                continue
            if len(page_slugs) >= 12:
                # Could be a real large category or the unfiltered fallback.
                # Only a full walk distinguishes them.
                total = len(collect_all_slugs(f"Category!{slug}"))
                if total >= baseline_total:
                    continue                   # filter ignored: it's everything
            hit = slug
            break

        if hit:
            resolved[ka] = hit
            if verbose:
                print(f"  ✓ {en:<22} → {hit}")
        else:
            unresolved.append((ka, en, candidates))
            if verbose:
                print(f"  ✗ {en:<22} none of {candidates}")
    return resolved, unresolved


def build_category_map(resolved: dict, verbose: bool = True) -> dict:
    """{offer_slug: [georgian category, ...]} — an offer may hold several."""
    mapping: dict[str, list[str]] = {}
    for ka, slug in resolved.items():
        slugs = collect_all_slugs(f"Category!{slug}")
        for offer_slug in slugs:
            mapping.setdefault(offer_slug, [])
            if ka not in mapping[offer_slug]:
                mapping[offer_slug].append(ka)
        if verbose:
            print(f"  {ka:<26} {len(slugs)}")
    return mapping


# Angular apps are frequently fronted by a prerender service that keys off
# the User-Agent. If TBC does that, a crawler UA gets HTML while a browser
# UA gets the shell — cheap to test, and decisive either way.
PROBE_AGENTS = {
    "Chrome (control)": HEADERS["User-Agent"],
    "Googlebot desktop": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "Googlebot smartphone": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "Bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "facebookexternalhit": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Twitterbot": "Twitterbot/1.0",
    "Prerender": "Prerender (+https://github.com/prerender/prerender)",
}

# beta.tbcbank.ge showed up in search results as a separate deployment and
# may render differently from production.
PROBE_HOSTS = [
    ("production /ka", "https://tbcbank.ge/ka/offers/all-offers"),
    ("beta /ka-GE", "https://beta.tbcbank.ge/ka-GE/offers/all-offers"),
    ("beta /en-US", "https://beta.tbcbank.ge/en-US/offers/all-offers"),
]


def _probe_render():
    """Finds any client identity or host that returns rendered offer HTML."""
    print("Looking for a request that returns rendered offers.\n")
    print(f"{'host':<18} {'user-agent':<24} {'bytes':>9}  offers")
    print("-" * 62)

    winners = []
    for host_name, url in PROBE_HOSTS:
        for ua_name, ua in PROBE_AGENTS.items():
            headers = dict(HEADERS)
            headers["User-Agent"] = ua
            try:
                resp = requests.get(url, params={"page": 1}, headers=headers,
                                    timeout=REQUEST_TIMEOUT)
                resp.encoding = "utf-8"
                body = resp.text
                n = len(extract_offer_slugs(body))
                size = f"{len(body):,}"
                status = "" if resp.status_code == 200 else f" HTTP {resp.status_code}"
            except requests.RequestException as e:
                size, n, status = "-", 0, f" {type(e).__name__}"
            marker = "  <<< RENDERS" if n > 0 else ""
            print(f"{host_name:<18} {ua_name:<24} {size:>9}  {n}{status}{marker}")
            if n > 0:
                winners.append((host_name, ua_name))
            time.sleep(DELAY_SECONDS)

    print()
    if winners:
        print("Rendered HTML from:")
        for host_name, ua_name in winners:
            print(f"  {host_name} + {ua_name}")
        print("\nSend this back — html_categories.py needs one header change.")
    else:
        print("Nothing returned rendered HTML.")
        print()
        print("The content is client-side only, so the remaining options are:")
        print("  1. Read the real filter request from your browser's DevTools")
        print("     (Network tab, apply a category filter, copy the request).")
        print("     This is the fastest route and takes about two minutes.")
        print("  2. Render the page with a headless browser (Playwright).")
        print("     Works, but adds a heavy dependency to the daily job.")


# --- bundle inspection ----------------------------------------------------
# The shell is 9 KB of nothing, but it loads the Angular bundles, and those
# contain the code that builds the filter request. Minification mangles
# variable names but leaves string literals intact — endpoint paths, query
# keys and separators all survive. Cheaper than asking a human to open
# DevTools, and it can only read public static assets.

_SCRIPT_SRC_RE = re.compile(r'<script[^>]+src="([^"]+\.js)"', re.I)
_MODULE_HREF_RE = re.compile(r'<link[^>]+href="([^"]+\.js)"', re.I)

# What we're hunting for, and why each one matters.
BUNDLE_PATTERNS = [
    ("api path",      re.compile(r'["\'`][^"\'`]{0,40}/api/v\d[^"\'`]{0,60}["\'`]')),
    ("marketing api", re.compile(r'["\'`][^"\'`]{0,60}marketing[^"\'`]{0,60}["\'`]')),
    ("offer endpoint", re.compile(r'["\'`][^"\'`]{0,60}entries/offer[^"\'`]{0,40}["\'`]')),
    ("filter separator", re.compile(r'["\'`]\s*[!$]\s*["\'`]')),
    ("filters key",   re.compile(r'\bfilters?\s*[:=]\s*[^,;)]{0,60}')),
    ("facet names",   re.compile(r'["\'`](?:Category|ProductType|OfferType|CardType)["\'`]')),
    ("segment key",   re.compile(r'\bsegment\s*[:=]\s*[^,;)]{0,40}')),
]

MAX_BUNDLE_BYTES = 12 * 1024 * 1024      # don't pull an unbounded amount
CONTEXT = 90


def _bundle_urls(html: str) -> list[str]:
    found = []
    for match in _SCRIPT_SRC_RE.findall(html) + _MODULE_HREF_RE.findall(html):
        if match.startswith("http"):
            url = match
        else:
            url = "https://tbcbank.ge/" + match.lstrip("/")
        if url not in found:
            found.append(url)
    return found


def _inspect_bundle():
    """Reads the app's JS looking for how it actually builds a filter request."""
    print("Fetching the shell to find its bundles...")
    html = fetch_listing(1)
    urls = _bundle_urls(html)
    print(f"  {len(urls)} script(s) referenced")
    for u in urls:
        print("   ", u)
    if not urls:
        print("\n  No <script src> found. First 800 chars:\n")
        print(html[:800])
        return

    total = 0
    hits: dict[str, set] = {name: set() for name, _ in BUNDLE_PATTERNS}
    for url in urls:
        if total > MAX_BUNDLE_BYTES:
            print("  (size cap reached, stopping)")
            break
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  {url.rsplit('/', 1)[-1]}: failed ({e})")
            continue
        body = resp.text
        total += len(body)
        print(f"  {url.rsplit('/', 1)[-1]}: {len(body):,} bytes")

        for name, pattern in BUNDLE_PATTERNS:
            for m in pattern.finditer(body):
                start = max(0, m.start() - CONTEXT)
                snippet = body[start:m.end() + CONTEXT]
                snippet = " ".join(snippet.split())
                hits[name].add(snippet)
        time.sleep(DELAY_SECONDS)

    print(f"\n  {total:,} bytes of JS scanned\n")
    for name, _ in BUNDLE_PATTERNS:
        found = sorted(hits[name])[:6]
        print(f"--- {name} ({len(hits[name])} match(es)) ---")
        if not found:
            print("  nothing")
        for snippet in found:
            print("  …" + snippet[:230] + "…")
        print()

    print("Send this output back. The goal is the request the app builds when")
    print("a category checkbox is ticked — endpoint path and parameter name.")


def _debug():
    """Shows exactly what the parser sees, for when something looks wrong."""
    print("Fetching the unfiltered listing...")
    html = fetch_listing(1)
    print(f"  {len(html):,} bytes")
    slugs = extract_offer_slugs(html)
    print(f"  {len(slugs)} offer links found")
    for s in slugs[:15]:
        print("   ", s)
    if not slugs:
        print("\n  NO OFFER LINKS. The page probably didn't server-render.")
        print("  First 1500 characters of the response:\n")
        print(html[:1500])
        return

    print("\nFetching Category!Auto...")
    filtered = fetch_listing(1, "Category!Auto")
    fslugs = extract_offer_slugs(filtered)
    print(f"  {len(fslugs)} offer links, 'no results' present: {_NO_RESULTS in filtered}")
    for s in fslugs[:15]:
        print("   ", s)
    print(f"\n  Different from unfiltered? {set(fslugs) != set(slugs)}")


def main():
    if "--inspect-bundle" in sys.argv:
        _inspect_bundle()
        return
    if "--probe-render" in sys.argv:
        _probe_render()
        return
    if "--debug" in sys.argv:
        _debug()
        return

    print("Walking the unfiltered listing to get a baseline...")
    baseline = collect_all_slugs(verbose=True)
    print(f"  {len(baseline)} offers total\n")
    if not baseline:
        print("No offers found in the HTML. Run with --debug to see why.")
        return

    print("Resolving category slugs...")
    resolved, unresolved = resolve_category_slugs(len(baseline))
    print()

    if not resolved:
        print("No category filter worked. Run --debug and send the output.")
        return

    print("Collecting offers per category...")
    mapping = build_category_map(resolved)

    os.makedirs(os.path.dirname(CATEGORY_MAP_FILE), exist_ok=True)
    with open(CATEGORY_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "resolved_slugs": resolved,
            "unresolved": [{"ka": ka, "en": en, "tried": c} for ka, en, c in unresolved],
            "baseline_offers": len(baseline),
            "categories": mapping,
        }, f, ensure_ascii=False, indent=2)

    covered = len(mapping)
    print(f"\n{covered}/{len(baseline)} offers tagged "
          f"({100 * covered // max(len(baseline), 1)}%)")
    if unresolved:
        print("Unresolved categories (empty, or the slug differs):")
        for ka, en, candidates in unresolved:
            print(f"  {en} ({ka}): tried {candidates}")
    print(f"\nSaved to {CATEGORY_MAP_FILE}")
    print("Run `python main.py` to apply it.")


if __name__ == "__main__":
    main()
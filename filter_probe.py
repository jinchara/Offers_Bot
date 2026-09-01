"""
filter_probe.py
Answers one question: how do you make TBC's JSON API actually apply a
filter?

    python filter_probe.py

WHY THIS EXISTS
---------------
`scraper.py --discover` showed every candidate slug returning the full
catalogue — including `TBCCard`, `Cashback` and `MasterCard`, which are
confirmed from a real filtered URL on TBC's own site. Confirmed slugs
cannot all be wrong at once, so the slugs aren't the problem: the API is
ignoring the `filters` parameter entirely and returning everything.

The likely cause is shape. Their URL encodes all facets as ONE
`$`-separated string:

    filters=Category!Auto,Shopping$ProductType!TBCCard$OfferType!Cashback

but the scraper sends a LIST, one string per facet:

    {"filters": ["Category!Auto", "ProductType!TBCCard"]}

An API that expects a string and receives a list will typically ignore it
rather than error, which is exactly the behaviour observed. That also means
the original `["ProductType!TBCCard"]` was never filtering anything — it
only looked like it worked because it returned everything and everything
was what we wanted.

This script tries each plausible shape against a category that should
return a small number of offers, and reports which ones narrow the result.
It writes nothing and changes nothing.

Paste the output back and the fix is a two-line change in scraper.py.
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

import json

import requests

from scraper import API_URL, HEADERS, REQUEST_TIMEOUT

# Flowers should be one of the smallest categories, so a working filter is
# obvious at a glance. Auto and Shopping are the two slugs confirmed from a
# real URL, so if any shape works it should work for these.
PROBES = ["Flowers", "Auto", "Shopping"]


def post(payload):
    """Returns totalCount, or an error string."""
    try:
        resp = requests.post(API_URL, json=payload, headers=HEADERS,
                             timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        return f"request failed: {e}"
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    try:
        body = resp.json()
    except ValueError:
        return "non-JSON response"
    paging = body.get("pagingDetails") or {}
    return paging.get("totalCount", len(body.get("list", [])))


def base(extra=None):
    payload = {"locale": "ka-GE", "segment": "All", "pageSize": 1, "pageIndex": 0}
    if extra:
        payload.update(extra)
    return payload


def main():
    baseline = post(base({"filters": []}))
    print(f"Baseline, no filters: {baseline}\n")
    if not isinstance(baseline, int) or baseline == 0:
        print("Could not read a baseline — stopping.")
        return

    # Each shape is a different guess at what the API wants. The name is
    # printed so the winning one can be copied straight into scraper.py.
    shapes = {
        "A  list of strings (current)":      lambda v: {"filters": [f"Category!{v}"]},
        "B  single $-joined string":         lambda v: {"filters": f"Category!{v}"},
        "C  string, key 'filter'":           lambda v: {"filter": f"Category!{v}"},
        "D  list of dicts":                  lambda v: {"filters": [{"name": "Category", "values": [v]}]},
        "E  dict of lists":                  lambda v: {"filters": {"Category": [v]}},
        "F  top-level 'categories'":         lambda v: {"categories": [v]},
        "G  top-level 'category'":           lambda v: {"category": v},
        "H  string + explicit locale param": lambda v: {"filters": f"Category!{v}", "page": 1},
    }

    winners = []
    for name, build in shapes.items():
        counts = []
        for value in PROBES:
            counts.append(post(base(build(value))))
        readable = "  ".join(
            f"{v}={c}" for v, c in zip(PROBES, counts)
        )
        narrowed = [
            c for c in counts if isinstance(c, int) and 0 < c < baseline
        ]
        varied = len({c for c in counts if isinstance(c, int)}) > 1
        verdict = "*** FILTERS ***" if (narrowed and varied) else ""
        print(f"{name:36} {readable}   {verdict}")
        if narrowed and varied:
            winners.append(name)

    print()
    if winners:
        print("Working shape(s):", ", ".join(winners))
        print("Send this output back — scraper.py needs a two-line change.")
    else:
        print("No payload shape filtered anything.")
        print()
        print("That means the JSON API has no filtering at all and the site")
        print("filters server-side while rendering the page. In that case the")
        print("category source becomes the HTML listing:")
        print("  https://tbcbank.ge/ka/offers/all-offers?filters=Category!Auto")
        print("which needs a different scraper path. Send the output either way.")


if __name__ == "__main__":
    main()
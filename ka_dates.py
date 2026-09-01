"""
ka_dates.py
Extracts campaign date ranges from TBC's Georgian offer copy.

WHY
---
Two situations where the API's own dates aren't enough:

  1. Migrating the old data. The previous code clamped `remaining_days` at
     zero, so 60 offers stored "0" with no way to tell "ends tonight" from
     "ended last November". The copy usually says outright:
     "15-16 ნოემბერს, გადაიხადე..." — that's recoverable.
  2. Cross-checking. When the API date and the advertised date disagree,
     that's worth surfacing rather than silently trusting one.

The parser is deliberately conservative. It returns None rather than
guessing, because a wrong date is worse than a missing one: a wrong date
silently moves an offer between "live" and "ended".

FORMS HANDLED
-------------
    21-23 აგვისტოს                    range inside one month
    13 აგვისტოდან 13 ნოემბრის ჩათვლით  range spanning months
    31 ოქტომბრიდან, 2 ნოემბრის ჩათვლით same, with punctuation
    27 ნოემბერს                        single day
    31 დეკემბრის ჩათვლით               end date only
    2026 წლის 24 ივნისის               explicit year

Georgian nouns inflect heavily (ნოემბერი / ნოემბერს / ნოემბრის /
ნოემბრიდან), so months are matched on stem. Note that several stems change
their vowel when inflected — ნოემბერი becomes ნოემბრის — which is why each
month lists more than one stem.
"""

import re
from datetime import date

# Stems chosen so that every inflected form in TBC's copy is covered, and
# no stem is a prefix of another month's stem.
MONTH_STEMS = {
    1: ["იანვ"],
    2: ["თებერვ"],
    3: ["მარტ"],
    4: ["აპრილ"],
    5: ["მაის"],
    6: ["ივნის"],
    7: ["ივლის"],
    8: ["აგვისტ"],
    9: ["სექტემბ"],
    10: ["ოქტომბ"],
    11: ["ნოემბ"],
    12: ["დეკემბ"],
}

_STEM_TO_MONTH = {stem: num for num, stems in MONTH_STEMS.items() for stem in stems}
_MONTH_ALT = "|".join(sorted(_STEM_TO_MONTH, key=len, reverse=True))

# A month word: stem plus whatever ending it happens to carry.
_MONTH = rf"(?:{_MONTH_ALT})[ა-ჰ]*"

_YEAR_RE = re.compile(r"(20\d{2})\s*წლის")

# "13 აგვისტოდან 13 ნოემბრის" — two full day+month pairs
_CROSS_MONTH_RE = re.compile(
    rf"(\d{{1,2}})\s+({_MONTH})\s*(?:[-–,]|\s)*\s*(\d{{1,2}})\s+({_MONTH})"
)
# "21-23 აგვისტოს" — day range, one month
_SAME_MONTH_RE = re.compile(rf"(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\s+({_MONTH})")
# "27 ნოემბერს" — single day
_SINGLE_RE = re.compile(rf"(\d{{1,2}})\s+({_MONTH})")

_MAX_DAYS_IN_MONTH = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}


def _month_number(word: str):
    lowered = word.lower()
    for stem, number in _STEM_TO_MONTH.items():
        if lowered.startswith(stem):
            return number
    return None


def _make_date(day: int, month: int, year: int):
    if not (1 <= month <= 12):
        return None
    if not (1 <= day <= _MAX_DAYS_IN_MONTH[month]):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _pick_year(month: int, day: int, reference: date, explicit_year: int | None,
               max_date: date | None = None):
    """
    Chooses the year for a day/month with no year written next to it.

    Offer copy is published shortly before the campaign runs, so the
    candidate closest to when we first saw the offer wins. Checking the
    year before and after the reference handles campaigns that straddle
    New Year — a December offer first seen in January belongs to the
    previous year, not the coming one.

    `max_date` is an upper bound the answer must respect. Migration needs
    it: those records are known to have already ended, so "15 ნოემბერს"
    must resolve to last November rather than the one coming up, even
    though the upcoming one is nearer to the reference date.
    """
    if explicit_year:
        return explicit_year
    candidates = []
    for year in (reference.year - 2, reference.year - 1, reference.year, reference.year + 1):
        made = _make_date(day, month, year)
        if made:
            candidates.append(made)
    if max_date:
        allowed = [d for d in candidates if d <= max_date]
        if allowed:
            return max(allowed).year
    if not candidates:
        return reference.year
    return min(candidates, key=lambda d: abs((d - reference).days)).year


def extract_date_range(text: str, reference: date | None = None,
                       max_date: date | None = None):
    """
    Returns (start, end) as `date` objects; either element may be None.

    `reference` anchors year inference — pass the offer's first_seen date.
    Defaults to today, which is right for freshly scraped copy.
    `max_date`, if given, forces the result not to land after that day.
    """
    if not text:
        return (None, None)
    reference = reference or date.today()
    explicit_year_match = _YEAR_RE.search(text)
    explicit_year = int(explicit_year_match.group(1)) if explicit_year_match else None

    # Most specific pattern first: two day+month pairs.
    match = _CROSS_MONTH_RE.search(text)
    if match:
        d1, m1_word, d2, m2_word = match.groups()
        m1, m2 = _month_number(m1_word), _month_number(m2_word)
        if m1 and m2:
            y1 = _pick_year(m1, int(d1), reference, explicit_year, max_date)
            start = _make_date(int(d1), m1, y1)
            # A range that runs "backwards" has crossed a year boundary.
            y2 = y1 + 1 if m2 < m1 else y1
            end = _make_date(int(d2), m2, y2)
            if start and end and end >= start:
                return (start, end)

    match = _SAME_MONTH_RE.search(text)
    if match:
        d1, d2, month_word = match.groups()
        month = _month_number(month_word)
        if month and int(d2) >= int(d1):
            year = _pick_year(month, int(d1), reference, explicit_year, max_date)
            start = _make_date(int(d1), month, year)
            end = _make_date(int(d2), month, year)
            if start and end:
                return (start, end)

    match = _SINGLE_RE.search(text)
    if match:
        day, month_word = match.groups()
        month = _month_number(month_word)
        if month:
            year = _pick_year(month, int(day), reference, explicit_year, max_date)
            single = _make_date(int(day), month, year)
            if single:
                return (single, single)

    return (None, None)


def infer_end_date(offer: dict, reference: date | None = None,
                   max_date: date | None = None):
    """
    Best-effort end date from an offer's title and description.

    Reads the title first — it's short and rarely contains an unrelated
    date — then the description.
    """
    reference = reference or (
        date.fromisoformat(offer["first_seen"]) if offer.get("first_seen") else None
    )
    for field in ("title", "description"):
        _, end = extract_date_range(offer.get(field) or "", reference, max_date)
        if end:
            return end
    return None

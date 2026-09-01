"""
tbc_taxonomy.py
TBC's own filter vocabulary — the thing that makes categorisation exact
instead of guessed.

HOW THEIR FILTERS WORK
----------------------
Their listing URL encodes filter state like this:

    ?segment=All&page=1&filters=Category!Auto,Shopping$ProductType!TBCCard
                                $OfferType!Cashback$CardType!CreditCard,MasterCard

  *  `$` separates facets
  *  `!` separates a facet from its values
  *  `,` separates multiple values inside one facet

The JSON API takes the same thing as a list, one string per facet:

    {"filters": ["Category!Auto,Shopping", "ProductType!TBCCard"]}

which is why the original scraper's `["ProductType!TBCCard"]` worked.

Values are **English PascalCase slugs**, not the Georgian labels shown in
the UI. That is what the first version of the category probe got wrong: it
sent `Category!ტექნიკა`, the API didn't recognise it, and an unrecognised
facet is ignored rather than rejected — so it returned the whole catalogue
and the probe correctly refused to trust it.

The Georgian and English labels below are transcribed from TBC's own
filter panel on /ka/ and /en/, in the same order, so the pairing is theirs
rather than a translation.

HOW TO READ A SLUG OFF THE SITE
-------------------------------
If a value shows up unresolved, don't guess — TBC prints the answer in the
address bar. Open the offers page, tick that one filter checkbox, and read
the URL:

    ...all-offers?segment=All&page=1&filters=Category!BeautyAndHealth
                                                      ^^^^^^^^^^^^^^^

Note the URL uses `!` while the API payload uses `:` — scraper.make_filter()
handles that translation, so copy only the value after the `!`.

SLUG CONFIDENCE
---------------
Confirmed against the live API by scraper.resolve_facet_values():

    Shopping 58    Transport 9     Education 2     Leisure 26
    Accessories 27 Clothes 98      OnlinePartners 41
    CafeAndRestaurant 28           Electronics 7   Home 29
    Auto 23        Groceries 4     ForKids 6       Entertainment 4
    Flowers 2      Developers 14   Perfume 13      Travel 56

    ProductType: TBCCard 332, TravelCard 21, TBCConceptCard 400,
                 CreditCard 320, PayLater 49, Installment 13, Crypto 1
    OfferType:   Discount 86, Cashback 372, PartnerOffers 308
    CardType:    CreditCard 24, MasterCard 9

Note the ka/en labels for CardType disagree — /ka/ says ვიზა where /en/
says "Credit Card" — and the slug that answers is `CreditCard`, not `Visa`.
TBC's own labelling, not a mistake on our side.

All values are now confirmed. The last two took the longest and revealed
the actual rule — see derive_slug() below. Single-word labels are unambiguous.
Multi-word ones are not — "Cafe and Restaurant" could be `CafeRestaurant`
or `CafeAndRestaurant` — so those carry several candidates and
`scraper.resolve_facet_values()` tries each against the live API and keeps
whichever actually returns a filtered subset. The resolved map is cached
in data/facet_map.json, so this costs a few extra requests once, not every
day, and the team can hand-edit it if TBC renames something.
"""

def derive_slug(english_label: str) -> str:
    """
    Turns an English filter label into TBC's slug.

    The rule, recovered after several wrong guesses: take the English
    label, capitalise the first letter of each word, and delete the spaces.
    Punctuation is left exactly as it is.

        "Cafe and Restaurant" -> "CafeAndRestaurant"
        "Online Partners"     -> "OnlinePartners"
        "Beauty & Health"     -> "Beauty&Health"
        "Pupil's Card"        -> "Pupil'sCard"

    Those last two are why this function exists. Every guess sanitised the
    "&" and the apostrophe away, because slugs usually don't contain them —
    but TBC's don't sanitise at all. Deriving mechanically beats guessing,
    so the derived form is appended to every candidate list below and will
    catch any category TBC adds later without anyone editing this file.
    """
    parts = english_label.split()
    return "".join(
        p[0].upper() + p[1:] if p and p[0].isalpha() else p
        for p in parts
    )


# --- Categories -----------------------------------------------------------
# (Georgian label, English label, [candidate slugs, best guess first])
CATEGORIES = [
    ("შოპინგი",                 "Shopping",            ["Shopping"]),
    ("ტრანსპორტი",              "Transport",           ["Transport", "Transportation"]),
    ("განათლება",               "Education",           ["Education"]),
    ("დასვენება",               "Leisure",             ["Leisure", "Recreation", "Rest"]),
    ("აქსესუარები",             "Accessories",         ["Accessories"]),
    ("ტანსაცმელი",              "Clothes",             ["Clothes", "Clothing", "Apparel"]),
    ("ონლაინ პარტნიორები",      "Online Partners",     ["OnlinePartners", "Online", "OnlinePartner"]),
    ("კაფე და რესტორანი",       "Cafe and Restaurant", ["CafeAndRestaurant", "CafeRestaurant",
                                                        "Restaurant", "CafeRestaurants"]),
    ("ტექნიკა",                 "Electronics",         ["Electronics", "Technics", "Technique"]),
    ("სახლი",                   "Home",                ["Home"]),
    ("ჯანმრთელობა და სილამაზე", "Beauty & Health",     ["Beauty&Health"]),
    ("ავტო",                    "Auto",                ["Auto"]),
    ("სურსათი",                 "Groceries",           ["Groceries", "Grocery", "Food"]),
    ("საბავშვო",                "For Kids",            ["ForKids", "Kids", "Children"]),
    ("გართობა",                 "Entertainment",       ["Entertainment", "Fun"]),
    ("ყვავილები",               "Flowers",             ["Flowers"]),
    ("დეველოპერები",            "Developers",          ["Developers", "Developer"]),
    ("პარფიუმერია",             "Perfume",             ["Perfume", "Perfumery"]),
    ("მოგზაურობა",              "Travel",              ["Travel"]),
]

# --- Product type ---------------------------------------------------------
PRODUCT_TYPES = [
    ("თიბისი ბარათი",        "TBC Card",         ["TBCCard"]),           # confirmed
    ("სამოგზაურო ბარათი",    "Travel Card",      ["TravelCard"]),
    ("თიბისი კონცეპტ ბარათი", "TBC Concept Card", ["TBCConceptCard", "ConceptCard"]),
    ("საკრედიტო ბარათი",     "Credit Card",      ["CreditCard"]),        # confirmed
    ("მოსწავლის ბარათი",     "Pupil's Card",     ["Pupil'sCard"]),
    ("განაწილება",           "Pay Later",        ["PayLater", "Ganatsileba"]),
    ("განვადება",            "Installment",      ["Installment", "Installments"]),
    ("კრიპტო",               "Crypto",           ["Crypto"]),
]

# --- Offer type -----------------------------------------------------------
OFFER_TYPES = [
    ("ფასდაკლება",              "Discount",       ["Discount"]),
    ("ქეშბექი",                 "Cashback",       ["Cashback"]),          # confirmed
    ("პარტნიორების შეთავაზება", "Partner Offers", ["PartnerOffers", "PartnerOffer", "Partner"]),
]

# --- Card type ------------------------------------------------------------
# TBC's own labels disagree between locales here: /ka/ lists ვიზა
# (Visa) and მასტერქარდი, while /en/ lists "Credit Card" and "MasterCard".
# A real URL contained `CardType!CreditCard,MasterCard`, so both spellings
# are offered as candidates and the resolver settles it.
CARD_TYPES = [
    ("ვიზა",         "Visa / Credit Card", ["Visa", "CreditCard"]),
    ("მასტერქარდი",  "MasterCard",         ["MasterCard", "Mastercard"]),  # confirmed
]

# --- Segments -------------------------------------------------------------
# Not a filter — a separate top-level query parameter. These are audience
# tiers, and the difference between them is commercially interesting:
# Concept is TBC's premium tier, so an offer that exists only in Concept is
# a deliberate retention play for high-value customers rather than mass
# acquisition.
SEGMENTS = [
    ("All",      "ყველა შეთავაზება", "All Offers"),
    ("Concept",  "კონცეპტი",         "Concept"),
    ("ForYouth", "ახალი თაობისთვის", "For Youth"),
]

SEGMENT_KEYS = [key for key, _, _ in SEGMENTS]

# Each offer in the API response carries its own `segments` array of
# Georgian labels, e.g.
#     "segments": [{"label": "ექსპატები", "isHidden": true},
#                  {"label": "კონცეპტი",  "isHidden": false}]
# That is cheaper and richer than querying ?segment= three times: it comes
# free with the listing, and it exposes audiences TBC doesn't show in the
# UI at all — "ექსპატები" (expats) is marked isHidden and has no tab.
SEGMENT_LABEL_TO_KEY = {
    "კონცეპტი": "Concept",
    "კონცეპტის პარტნიორები": "Concept",
    "ახალი თაობისთვის": "ForYouth",
    "ახალი თაობა": "ForYouth",
    "ექსპატები": "Expats",
    "ემიგრანტები": "Emigrants",
}

# Anything not in the map above is kept verbatim rather than dropped, so a
# new audience shows up in the data instead of silently disappearing.
SEGMENT_LABELS_EXTRA = {
    "Expats": "ექსპატები",
    "Emigrants": "ემიგრანტები",
}


def segment_key(label: str) -> str:
    return SEGMENT_LABEL_TO_KEY.get((label or "").strip(), (label or "").strip())
SEGMENT_LABELS_KA = {key: ka for key, ka, _ in SEGMENTS}

def _with_derived(vocabulary):
    """Appends the mechanically derived slug wherever it isn't already tried."""
    out = []
    for ka, en, candidates in vocabulary:
        derived = derive_slug(en)
        if derived not in candidates:
            candidates = candidates + [derived]
        out.append((ka, en, candidates))
    return out


CATEGORIES = _with_derived(CATEGORIES)
PRODUCT_TYPES = _with_derived(PRODUCT_TYPES)
OFFER_TYPES = _with_derived(OFFER_TYPES)
CARD_TYPES = _with_derived(CARD_TYPES)

# Facet name -> the vocabulary for it. Used to drive both discovery and the
# daily tagging pass.
FACETS = {
    "Category": CATEGORIES,
    "ProductType": PRODUCT_TYPES,
    "OfferType": OFFER_TYPES,
    "CardType": CARD_TYPES,
}

# Georgian label lookups, so stored data and the UI stay in Georgian even
# though the wire format is English.
KA_LABEL = {
    facet: {slug_candidates[0]: ka for ka, _, slug_candidates in vocabulary}
    for facet, vocabulary in FACETS.items()
}


def ka_label(facet: str, slug: str) -> str:
    """Georgian label for a resolved slug, falling back to the slug itself."""
    return KA_LABEL.get(facet, {}).get(slug, slug)


def build_ka_lookup(resolved: dict) -> dict:
    """
    Maps resolved slugs back to Georgian labels.

    `resolved` is {facet: {canonical_slug: working_slug}} as produced by
    scraper.resolve_facet_values(). The working slug is what the API
    accepted, which may not be our first candidate, so the reverse lookup
    has to be built from the resolution result rather than assumed.
    """
    lookup = {}
    for facet, vocabulary in FACETS.items():
        lookup[facet] = {}
        for ka, _en, candidates in vocabulary:
            canonical = candidates[0]
            working = (resolved.get(facet) or {}).get(canonical, canonical)
            lookup[facet][working] = ka
    return lookup
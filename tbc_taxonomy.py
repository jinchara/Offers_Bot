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

SLUG CONFIDENCE
---------------
Two slugs are confirmed from a real URL: `Auto` and `Shopping`. The rest
are inferred from the English labels. Single-word labels are unambiguous.
Multi-word ones are not — "Cafe and Restaurant" could be `CafeRestaurant`
or `CafeAndRestaurant` — so those carry several candidates and
`scraper.resolve_facet_values()` tries each against the live API and keeps
whichever actually returns a filtered subset. The resolved map is cached
in data/facet_map.json, so this costs a few extra requests once, not every
day, and the team can hand-edit it if TBC renames something.
"""

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
    ("ჯანმრთელობა და სილამაზე", "Beauty & Health",     ["BeautyHealth", "BeautyAndHealth",
                                                        "HealthBeauty", "HealthAndBeauty", "Beauty"]),
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
    ("მოსწავლის ბარათი",     "Pupil's Card",     ["PupilCard", "PupilsCard", "StudentCard"]),
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
SEGMENT_LABELS_KA = {key: ka for key, ka, _ in SEGMENTS}

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

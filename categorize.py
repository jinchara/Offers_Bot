"""
categorize.py
Zero-cost keyword-based categorizer + cashback/cap extractor.

TBC's filter widget exposes these exact categories (from the listing page):
შოპინგი, ტრანსპორტი, განათლება, დასვენება, აქსესუარები, ტანსაცმელი,
ონლაინ პარტნიორები, კაფე და რესტორანი, ტექნიკა, სახლი,
ჯანმრთელობა და სილამაზე, ავტო, სურსათი, საბავშვო, გართობა,
ყვავილები, დეველოპერები, პარფიუმერია, მოგზაურობა

Since categories aren't printed on each offer card, we guess from the
title/brand/description text using keyword hints. This is heuristic, not
authoritative — good enough for grouping in reports, not perfect. Extend
CATEGORY_KEYWORDS as you notice misclassifications.

Order matters: dicts are matched top-to-bottom, so more specific/narrow
categories are listed before broad catch-all ones (e.g. "საბავშვო" before
"შოპინგი"), otherwise a generic keyword would steal the match first.
"""

import re

CATEGORY_KEYWORDS = {
    "საბავშვო": [
        "kids", "baby", "საბავშვო", "ბავშვ", "child", "ბავშვთა",
        "სათამაშო", "toy", "pampers", "ბავშვის",
    ],
    "პარფიუმერია": [
        "parfum", "perfum", "პარფიუმ", "sivopa", "sephora", "ნიშ",
        "cosmetics", "კოსმეტიკ", "iherb",
    ],
    "ჯანმრთელობა და სილამაზე": [
        "beauty", "სილამაზ", "clinic", "კლინიკ", "pharma", "აფთიაქ",
        "dental", "სტომატოლოგ", "gym", "fitness", "pilates",
        "wellness", "სამედიცინო", "medical", "health", "ჯანმრთელობ",
        "optic", "ოპტიკ", "hair", "თმის", "სალონ", "salon", "spa", "სპა",
    ],
    "აქსესუარები": [
        "accessor", "აქსესუარ", "watch", "საათ", "jewel", "სამკაულ",
        "bag", "ჩანთ", "sunglass", "მზის სათვალ",
    ],
    "ტანსაცმელი": [
        "fashion", "clothing", "ტანსაცმელ", "shoe", "ფეხსაცმ",
        "boutique", "ბუტიკ", "sportswear", "სპორტული ტანსაცმ",
    ],
    "ტექნიკა": [
        "icity", "electronics", "ტექნიკ", "phone", "ტელეფონ", "laptop",
        "computer", "კომპიუტერ", "smartphone", "gadget", "alta",
        "appliance", "ბითუმი", "samsung", "apple store", "xiaomi",
    ],
    "სახლი": [
        "furniture", "ავეჯ", "home decor", "ინტერიერ", "interior",
        "საოჯახო", "household", "kitchen", "სამზარეულო", "домашн",
        "carpet", "ხალიჩ", "ჭურჭელ", "kerama", "ceramic", "კერამ",
        "კაფელ", "santehnik", "სანტექნიკ", "renovation", "რემონტ",
        "tile", "ფილა",
    ],
    "ავტო": [
        "auto ", "ავტო", " car ", "car wash", "სახდელ", "fuel",
        "საწვავ", "tire", "საბურავ", "ავტოსერვის", "auto service",
        "socar", "wissol", "rompetrol", "gulf",
    ],
    "ტრანსპორტი": [
        "ტრანსპორტ", "taxi", "ტაქსი", "bolt", "yandex go", "transport",
        "მეტრო", "metro", "მგზავრობ",
    ],
    "კაფე და რესტორანი": [
        "mcdonald", "restaurant", "რესტორან", "cafe", "კაფე", "wasabi",
        "wok", "coffee", "yotel", "sushi", "pizza", "burger", "bakery",
        "საცხობ", "საკონდიტრო", "confection", "food court",
    ],
    "სურსათი": [
        "market", "სუპერმარკეტ", "food", "საკვებ", "grocery", "carrefour",
        "spar", "nikora", "goodwill", "smart", "agrohub", "ბაზარ",
        "ბაზრობა",
    ],
    "ყვავილები": [
        "flower", "ყვავილ", "florist", "ბუკეტ", "bouquet",
    ],
    "გართობა": [
        "cinema", "კინო", "entertainment", "game", "თამაშ", "theatre",
        "თეატრ", "concert", "კონცერტ", "amusement", "park", "ატრაქციონ",
        "bowling", "ბოულინგ", "trampoline",
    ],
    "დასვენება": [
        "spa", "სპა", "hotel", "sails", "grandeur", "sasturmo",
        "სასტუმრო", "resort", "ბანაკ", "camping", "beach", "პლაჟ",
        "yotel", "posta hotel",
    ],
    "მოგზაურობა": [
        "travel", "მოგზაურ", "flight", "aviabilet", "ავიაბილეთ", "tour",
        "ტურ", "wizz", "turkish airlines", "airline", "ავიაკომპან",
        "visa", "ვიზ", "booking.com",
    ],
    "განათლება": [
        "education", "განათლებ", "school", "სკოლ", "university",
        "უნივერსიტეტ", "course", "კურს", "language", "ენის შესწავლ",
        "training", "ტრენინგ",
    ],
    "დეველოპერები": [
        "developer", "დეველოპერ", "apartment", "ბინ", "real estate",
        "უძრავი ქონებ", "residence", "საცხოვრებელი კომპლექს",
    ],
    "ონლაინ პარტნიორები": [
        "online", "ონლაინ", "e-commerce", "delivery", "wolt", "glovo",
        "amazon", "aliexpress",
    ],
    "შოპინგი": [
        "mall", "მოლ", "shopping", "შოპინგ", "outlet", "department store",
    ],
}


def categorize(offer: dict) -> str:
    haystack = (
        f"{offer.get('title') or ''} "
        f"{offer.get('brand') or ''} "
        f"{offer.get('description') or ''}"
    ).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in haystack:
                return category
    return "სხვა"  # "other" / uncategorized


# --- Cashback / cap extraction -------------------------------------------
# Heuristic, best-effort parsing of TBC's Georgian offer copy. Common
# phrasing seen in real offers: "დაიბრუნეთ 30% ულიმიტოდ და მომენტალურად",
# "დაიბრუნე 20%". Cap phrasing varies a lot, so cap_amount is best-effort
# and can be None even for offers that do have a cap.

_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
_UNLIMITED_RE = re.compile(r"ულიმიტ")
_CAP_AMOUNT_RE = re.compile(r"(\d[\d\s.,]{0,8})\s*(?:₾|ლარ)")


def extract_offer_economics(offer: dict) -> dict:
    """
    Returns {"cashback_percent": int|None, "cap_unlimited": bool,
    "cap_amount": float|None} parsed heuristically from the offer's
    title/description text.
    """
    haystack = f"{offer.get('title') or ''} {offer.get('description') or ''}"

    percents = [int(m) for m in _PERCENT_RE.findall(haystack)]
    # Filter out obviously-non-cashback percentages (e.g. VAT mentions, etc.)
    percents = [p for p in percents if 0 < p <= 100]
    cashback_percent = max(percents) if percents else None

    cap_unlimited = bool(_UNLIMITED_RE.search(haystack))

    cap_amount = None
    if not cap_unlimited:
        match = _CAP_AMOUNT_RE.search(haystack)
        if match:
            raw = match.group(1).replace(" ", "").replace(",", ".")
            try:
                cap_amount = float(raw)
            except ValueError:
                cap_amount = None

    return {
        "cashback_percent": cashback_percent,
        "cap_unlimited": cap_unlimited,
        "cap_amount": cap_amount,
    }
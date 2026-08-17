"""
categorize.py
Zero-cost keyword-based categorizer.

TBC's filter widget exposes these exact categories (from the listing page):
შოპინგი, ტრანსპორტი, განათლება, დასვენება, აქსესუარები, ტანსაცმელი,
ონლაინ პარტნიორები, კაფე და რესტორანი, ტექნიკა, სახლი,
ჯანმრთელობა და სილამაზე, ავტო, სურსათი, საბავშვო, გართობა,
ყვავილები, დეველოპერები, პარფიუმერია, მოგზაურობა

Since categories aren't printed on each offer card, we guess from the
brand/title text using keyword hints. This is heuristic, not authoritative —
good enough for grouping in reports, not perfect. Extend CATEGORY_KEYWORDS
as you notice misclassifications.
"""

CATEGORY_KEYWORDS = {
    "კაფე და რესტორანი": [
        "mcdonald", "restaurant", "რესტორან", "cafe", "კაფე", "wasabi", "wok",
        "coffee", "yotel", "sushi", "pizza", "burger",
    ],
    "დასვენება": [
        "spa", "სპა", "hotel", "hotel", "sails", "grandeur", "pilates",
        "fitness", "wellness", "სასტუმრო",
    ],
    "ტანსაცმელი": ["fashion", "wear", "clothing", "ტანსაცმელ", "shoe", "ფეხსაცმ"],
    "ტექნიკა": ["icity", "electronics", "ტექნიკ", "phone", "laptop", "computer"],
    "მოგზაურობა": ["travel", "მოგზაურ", "flight", "tour", "hotel"],
    "ჯანმრთელობა და სილამაზე": [
        "beauty", "სილამაზ", "clinic", "კლინიკ", "pharma", "აფთიაქ",
        "pilates", "gym", "fitness", "snap",
    ],
    "სურსათი": ["market", "სუპერმარკეტ", "food", "საკვებ", "grocery"],
    "საბავშვო": ["kids", "baby", "საბავშვო", "child"],
    "გართობა": ["cinema", "კინო", "entertainment", "game", "თამაშ"],
    "ავტო": ["auto", "car", "ავტო", "fuel", "საწვავ"],
    "ონლაინ პარტნიორები": ["online", "ონლაინ", "e-commerce", "delivery"],
}


def categorize(offer: dict) -> str:
    haystack = f"{offer.get('title') or ''} {offer.get('brand') or ''}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in haystack:
                return category
    return "სხვა"  # "other" / uncategorized

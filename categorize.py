"""
categorize.py
Assigns each TBC offer one of TBC's own 19 categories.

WHY THE OLD VERSION MIS-CATEGORISED
-----------------------------------
The previous implementation did `if keyword in haystack` over a plain
lowercased string and returned on the *first* match, walking categories in
dict order. Two consequences:

  * Substring collisions. "მეტრო" is a ტრანსპორტი keyword, and
    "მეტრომარტში" contains it, so მეტრომარტი — an electronics and
    homeware retailer — was filed under transport. Same class of bug put
    "smart" inside "smartphone" into სურსათი and "ბინ" inside "კაბინეტი"
    into დეველოპერები.
  * First-match-wins. A description mentioning "ონლაინ" anywhere beat
    every more specific signal later in the dict, and 62% of offers
    (335/541) fell through to "სხვა".

THE REPLACEMENT
---------------
Four layers, most trustworthy first:

  1. data/category_overrides.json — manual corrections by the team. Always
     wins. Nobody has to edit Python to fix one merchant.
  2. api_categories — TBC's own tags, when scraper.py manages to read them
     off the filter facets. This is ground truth.
  3. BRAND_CATEGORIES — a curated merchant dictionary. Brand names are far
     more reliable than free text.
  4. Weighted keyword scoring over tokens, not raw substrings, with veto
     rules. Every category is scored; the winner is the highest total, not
     whichever happened to be checked first.

Matching is token-based. Georgian is heavily suffixed
(მეტრომარტი -> მეტრომარტში -> მეტრომარტიდან), so patterns come in three
forms:
    "მეტრო"        exact token only    — will NOT match მეტრომარტში
    "მეტრომარტ*"   token prefix        — matches all its case endings
    "auto service" phrase              — plain substring, spaces included
"""

import json
import os
import re

# --- TBC's real category list (from the filter panel on their site) -------
SHOPPING = "შოპინგი"
TRANSPORT = "ტრანსპორტი"
EDUCATION = "განათლება"
LEISURE = "დასვენება"
ACCESSORIES = "აქსესუარები"
CLOTHING = "ტანსაცმელი"
ONLINE = "ონლაინ პარტნიორები"
FOOD_SERVICE = "კაფე და რესტორანი"
ELECTRONICS = "ტექნიკა"
HOME = "სახლი"
HEALTH_BEAUTY = "ჯანმრთელობა და სილამაზე"
AUTO = "ავტო"
GROCERY = "სურსათი"
KIDS = "საბავშვო"
FUN = "გართობა"
FLOWERS = "ყვავილები"
DEVELOPERS = "დეველოპერები"
PERFUME = "პარფიუმერია"
TRAVEL = "მოგზაურობა"
OTHER = "სხვა"

TBC_CATEGORIES = [
    SHOPPING, TRANSPORT, EDUCATION, LEISURE, ACCESSORIES, CLOTHING, ONLINE,
    FOOD_SERVICE, ELECTRONICS, HOME, HEALTH_BEAUTY, AUTO, GROCERY, KIDS,
    FUN, FLOWERS, DEVELOPERS, PERFUME, TRAVEL,
]

OVERRIDES_FILE = os.path.join(
    os.path.dirname(__file__), "data", "category_overrides.json"
)
# Written by html_categories.py — TBC's own categorisation, scraped from
# their rendered listing because their JSON API cannot filter.
CATEGORY_MAP_FILE = os.path.join(
    os.path.dirname(__file__), "data", "category_map.json"
)


# =========================================================================
# Layer 3 — merchant dictionary
# =========================================================================
# Keys are normalised brand names (lowercase, punctuation stripped). Built
# by reading the ~300 distinct partners actually present in offers.json.
# Add a line here when a new merchant shows up; it is cheaper and more
# precise than inventing another keyword.

_RAW_BRAND_CATEGORIES = {
    # --- ტექნიკა ---------------------------------------------------------
    "მეტრომარტი": ELECTRONICS,          # the bug that started this rewrite
    "მეგატექნიკა": ELECTRONICS,
    "გრანდ ელექტრონიქსი": ELECTRONICS,
    "აიტექნიკსი": ELECTRONICS,
    "itechnics": ELECTRONICS,
    "აიმობაილი": ELECTRONICS,
    "აიქონიქ": ELECTRONICS,
    "ალგორითმი": ELECTRONICS,
    "pc room": ELECTRONICS,
    "პიკი": ELECTRONICS,
    "ქონექთი": ELECTRONICS,
    "supersim": ELECTRONICS,
    "ველი სთორი": ELECTRONICS,
    "veli store": ELECTRONICS,
    "ალტა": ELECTRONICS,
    "ელიტი": ELECTRONICS,
    "ელიტ ელექტრონიქსი": ELECTRONICS,
    "კონტაქტი": ELECTRONICS,
    "ტეკა": ELECTRONICS,

    # --- ტანსაცმელი ------------------------------------------------------
    "ნაიკი": CLOTHING, "პუმა": CLOTHING, "ნიუ ბალანსი": CLOTHING,
    "კონვერსი": CLOTHING, "ჰუმელი": CLOTHING, "ზე ნორს ფეის": CLOTHING,
    "კოლუმბია": CLOTHING, "ტიმბერლენდი": CLOTHING, "ჯეოქსი": CLOTHING,
    "ბატა": CLOTHING, "სკარპიერა": CLOTHING, "ქოლ ით სფრინგ": CLOTHING,
    "ბალდი": CLOTHING, "ლევისი": CLOTHING, "ლი  ვრანგლერი": CLOTHING,
    "ტომი ჯინსი": CLOTHING, "ჯეკ  ჯონსი": CLOTHING, "ჯი სთარ როუ": CLOTHING,
    "დიზელ": CLOTHING, "მავი": CLOTHING, "რიფლეი": CLOTHING,
    "სკოჩ  სოდა": CLOTHING, "სუპერდრაი საქართველო": CLOTHING,
    "ბერშკა": CLOTHING, "სტრადივარიუსი": CLOTHING, "ფულ  ბეარ": CLOTHING,
    "მარკს სპენსერ": CLOTHING, "მონსუნ": CLOTHING, "პატრიცია პეპე": CLOTHING,
    "პინკო": CLOTHING, "პიერ კარდენი": CLOTHING, "დონა კარანი": CLOTHING,
    "ჯორდანო": CLOTHING, "ნექსთი": CLOTHING, "გენტი": CLOTHING,
    "ქომოუდი": CLOTHING, "ბრენდ არ": CLOTHING, "პრიმიჯი": CLOTHING,
    "ტანსაცმლის გალერეა": CLOTHING, "ჯინს გალერი": CLOTHING,
    "ჯინსები": CLOTHING, "კორსო იტალია": CLOTHING, "ტრიუმფი": CLOTHING,
    "პენტი": CLOTHING, "ალტერსოქსი": CLOTHING, "მიქსონი": CLOTHING,
    "დრესაპი": CLOTHING, "დოთსი": CLOTHING, "ჰაბადა": CLOTHING,
    "ბიჯი სთორი": CLOTHING, "პანცილიონი": CLOTHING, "სოფიკო": CLOTHING,

    # --- საბავშვო --------------------------------------------------------
    "ოკაიდი": KIDS, "ჟაკადი": KIDS, "სერჟანტმეიჯორ": KIDS,
    "ორიჯინალ მარინსი": KIDS, "მინილენდი": KIDS, "გიგლსი": KIDS,
    "kids dream": KIDS, "ლოლი": KIDS,

    # --- აქსესუარები -----------------------------------------------------
    "პანდორა": ACCESSORIES, "რობერტო ბრავო": ACCESSORIES,
    "სამსონაიტი": ACCESSORIES, "ჩარლს  კეის": ACCESSORIES,
    "სათვალის გალერეა": ACCESSORIES, "კენარი": ACCESSORIES,
    "ტრესორი": ACCESSORIES, "სკივრი": ACCESSORIES, "ალკორიუმი": ACCESSORIES,

    # --- ჯანმრთელობა და სილამაზე -----------------------------------------
    "ჯიპისი": HEALTH_BEAUTY,           # GPC pharmacy chain, not "GPS"
    "პსპ": HEALTH_BEAUTY,              # PSP pharmacy chain
    "ბოდი შოპი": HEALTH_BEAUTY, "ივ როშე": HEALTH_BEAUTY,
    "ფლორმარ": HEALTH_BEAUTY, "ანე როშ": HEALTH_BEAUTY,
    "კოსმო": HEALTH_BEAUTY, "ნეილ სანი": HEALTH_BEAUTY,
    "ნოორ ნეილს": HEALTH_BEAUTY, "სმაილ ქეარი": HEALTH_BEAUTY,
    "ჰერ სთორი": HEALTH_BEAUTY, "ტოტალ შარმი": HEALTH_BEAUTY,
    "ora pilates": HEALTH_BEAUTY, "ავლაბ": HEALTH_BEAUTY,
    "ბი იო": HEALTH_BEAUTY, "დენსი": HEALTH_BEAUTY,
    "ქალთა ბედნიერება": HEALTH_BEAUTY,

    # --- პარფიუმერია -----------------------------------------------------
    "არომატეკა": PERFUME, "aromateque": PERFUME, "არომაკო": PERFUME,
    "პარფოის": PERFUME, "ეტერნა": PERFUME, "ლალინ გეორგია": PERFUME,

    # --- სურსათი ---------------------------------------------------------
    "სნექი": GROCERY, "ბადაგი": GROCERY, "პრემიქსი": GROCERY,
    "მეამა": GROCERY, "მეღვინეობა ხარება": GROCERY, "შატო მერე": GROCERY,
    "მტევინო": GROCERY, "სევსამორა": GROCERY, "ნინეა": GROCERY,

    # --- კაფე და რესტორანი ------------------------------------------------
    "ვასაბი": FOOD_SERVICE, "ბანგკოკი": FOOD_SERVICE, "პაცცა": FOOD_SERVICE,
    "ლუკა პოლარე": FOOD_SERVICE, "დოდონატი": FOOD_SERVICE,
    "დანკინი": FOOD_SERVICE, "ლე პონჩიკი": FOOD_SERVICE,
    "პანუოცო": FOOD_SERVICE, "მანჩიზი": FOOD_SERVICE,
    "ძველი სუფრა": FOOD_SERVICE, "ჭიტა": FOOD_SERVICE,
    "ცეცხლი აინთო": FOOD_SERVICE, "პეპელა": FOOD_SERVICE,
    "ჯეკი ჩანი": FOOD_SERVICE, "ჩიკორი": FOOD_SERVICE, "გასა": FOOD_SERVICE,
    "წრე": FOOD_SERVICE, "მულტი": FOOD_SERVICE,

    # --- სახლი -----------------------------------------------------------
    "პარკეტის გალერია": HOME, "რუმ დიზაინი": HOME, "სლიფ ენდ ბედ": HOME,
    "ბერგჰოფ": HOME, "შტელცეს სახლი": HOME, "შპს თბილისი ლაითინგ": HOME,
    "ბელჰაუსი": HOME, "ფერრო": HOME, "გლას არტ სტუდიო": HOME,
    "kerama marazzi": HOME, "ლენდსქეიფს": HOME, "ჰარმოსფერო": HOME,

    # --- ავტო ------------------------------------------------------------
    "mazda": AUTO, "volvo": AUTO, "e-motors georgia": AUTO,
    "emotors georgia": AUTO, "გრეიდერი": AUTO,

    # --- მოგზაურობა ------------------------------------------------------
    "ჯორჯიან ეარვეის": TRAVEL, "airalo": TRAVEL, "ვოიაჟერი": TRAVEL,
    "მაგელანი": TRAVEL, "tripcamp": TRAVEL, "easy jet": TRAVEL,
    "easyjet": TRAVEL, "hertz": TRAVEL, "avis": TRAVEL,
    "global blue": TRAVEL, "fast track": TRAVEL,

    # --- დასვენება -------------------------------------------------------
    "ბესთ ვესტერნ პრემიერ ბათუმი": LEISURE, "ბესთ ვესტერნ გუდაური": LEISURE,
    "ბრისტოლ ბაკურიანი": LEISURE, "ჰილტოპ ოქროყანა": LEISURE,
    "ვილა მოსავალი": LEISURE, "რანჩო ვარიანში": LEISURE,
    "ბანგურიანი მესტიაში": LEISURE, "ახალი საირმე": LEISURE,
    "კოხტა პლაზა": LEISURE, "king david pool": LEISURE,
    "ვაკის საცურაო აუზი": LEISURE, "ნამი 8": LEISURE,

    # --- გართობა ---------------------------------------------------------
    "ადრენალინი": FUN, "xtreme": FUN, "საბაგირო გზა არგო": FUN,
    "სკუტ სკუტი": FUN, "lovestars": FUN, "puzz": FUN,
    "სქაილანთერნ": FUN, "kinoafisha": FUN, "biletebi": FUN,

    # --- დეველოპერები ----------------------------------------------------
    "ლისი დეველოპმენტი": DEVELOPERS,
    "ბუკნარი  ლისი დეველოპმენტისგან": DEVELOPERS,

    # --- განათლება -------------------------------------------------------
    "აზროვნების აკადემია": EDUCATION, "მაისტარტაპ": EDUCATION,

    # --- შოპინგი ---------------------------------------------------------
    "სითი მოლი": SHOPPING, "გალერია თბილისი": SHOPPING,
    "კაპიტალ სქვერი": SHOPPING, "მინისო": SHOPPING,
    "სუვენირების მაღაზია არგო": SHOPPING, "ისთ ფოინთი": SHOPPING,
    "თბილისი მოლი": SHOPPING, "ბიბლუსი": SHOPPING, "საბა": SHOPPING,
    "ვანპრაისი": SHOPPING,

    # --- second pass: brands seen in the live data ------------------------
    # ტანსაცმელი
    "ზარა": CLOTHING, "მანგო": CLOTHING, "მასიმო დუტი": CLOTHING,
    "ადიდასი": CLOTHING, "ლაკოსტი": CLOTHING, "კელვინ კლაინი": CLOTHING,
    "იუ ეს პოლო": CLOTHING, "ვერო მოდა": CLOTHING, "ეტამი": CLOTHING,
    "კიაბი": CLOTHING, "მატალანი": CLOTHING, "ოვს": CLOTHING,
    "ოიშო": CLOTHING, "იპეკიოლი": CLOTHING, "ლა ვი ენ როუზ": CLOTHING,
    "EA7 ემპორიო არმანი": CLOTHING, "Ecco Geox": CLOTHING,
    "ალდო": CLOTHING, "ვორტმანი": CLOTHING, "რექლესი": CLOTHING,
    "რუთსი": CLOTHING, "კაბა": CLOTHING, "დრესაპ აუთლეტი": CLOTHING,
    "დრესაპ ბათუმი აუთლეტ": CLOTHING, "ლი / ვრანგლერი": CLOTHING,
    "ჯეკ & ჯონსი": CLOTHING, "ფულ & ბეარ": CLOTHING,
    "სკოჩ & სოდა": CLOTHING, "ბი&ჯი სთორი": CLOTHING,
    # აქსესუარები
    "ჩარლს & კეის": ACCESSORIES, "სანგლას ჰატი": ACCESSORIES,
    "MessyWeekend": ACCESSORIES, "G-SHOCK": ACCESSORIES,
    "ართთაიმი": ACCESSORIES, "პარკერ ჯორჯია": ACCESSORIES,
    "პენდანტი": ACCESSORIES,
    # ტექნიკა
    "ბეკო": ELECTRONICS, "მიდეა": ELECTRONICS, "ვესტელი": ELECTRONICS,
    "აიმარტი": ELECTRONICS, "აისითი": ELECTRONICS, "iPlus": ELECTRONICS,
    # სახლი
    "ენზა ჰოუმი": HOME, "ინგლიშ ჰოუმი": HOME, "ზარა ჰოუმ": HOME,
    "ესპაჩო": HOME, "ესტია": HOME, "დომინო": HOME, "კომფორტერი": HOME,
    "იატაშ ბედინგი": HOME, "კერამა მარაცი": HOME,
    "Design Institute": HOME, "Designinstitute.ge": HOME,
    # ჯანმრთელობა და სილამაზე
    "ფარმადეპო": HEALTH_BEAUTY, "კიკო მილანო": HEALTH_BEAUTY,
    "ბიუთი ბარი": HEALTH_BEAUTY, "თაიმლეს ბიუთი": HEALTH_BEAUTY,
    "დენტალ სთარი": HEALTH_BEAUTY, "ვაით სტუდიო": HEALTH_BEAUTY,
    "ვისტამედი": HEALTH_BEAUTY, "ფლორმარი": HEALTH_BEAUTY,
    "Cosmo.com.ge": HEALTH_BEAUTY,
    # პარფიუმერია
    "Atelier Rebul": PERFUME, "ლუტეცია": PERFUME,
    # სურსათი
    "კარფური": GROCERY, "სმარტი": GROCERY, "აგროჰაბი": GROCERY,
    "ვაინ მარკეტი": GROCERY, "ვისკის სახლი": GROCERY,
    "თბილღვინო": GROCERY,
    # კაფე და რესტორანი
    "ვენდის": FOOD_SERVICE, "Fire Wok": FOOD_SERVICE,
    "Blue Elephant": FOOD_SERVICE,
    # ავტო
    "გალფი": AUTO, "ვიანორი": AUTO, "თეგეტა შოპი": AUTO,
    "ტოიოტა ცენტრი თბილისი": AUTO, "SR Auto": AUTO, "მაიავტო.ჯი": AUTO,
    "მაიფართს.ჯი": AUTO,
    # საბავშვო
    "ატომ ქიდს": KIDS, "ბამბინო": KIDS, "ქიდს გალერი": KIDS,
    "XS Toys": KIDS,
    # გართობა
    "კავეას კინოთეატრები": FUN, "კინოაფიშა.ჯი": FUN,
    "Tatuza Jazz Club": FUN, "Setanta Sports": FUN,
    # დასვენება
    "Crowne Plaza Borjomi": LEISURE, "ჯორჯია პალასი": LEISURE,
    "La Quinta by Wyndham Batumi": LEISURE,
    # მოგზაურობა
    "TKTFly": TRAVEL,
    # განათლება
    "სმარტაკადემია.ჯი": EDUCATION,
    # ონლაინ პარტნიორები
    "მაიმარკეტი": ONLINE, "მაიშოფ.ჯი": ONLINE, "კივიპოსტ.ჯი": ONLINE,
    # დეველოპერები
    "ბუკნარი - ლისი დეველოპმენტისგან": DEVELOPERS,
}

# Keys are written above the way TBC writes them; normalising here means
# nobody has to hand-apply the punctuation rules when adding a merchant.
BRAND_CATEGORIES = {}


# =========================================================================
# Layer 4 — weighted keyword rules
# =========================================================================
# (pattern, weight). Weight reflects how diagnostic the word is on its own:
#   4 = names the category outright   2 = strong hint   1 = weak hint

KEYWORD_RULES = {
    KIDS: [
        ("საბავშვო", 4), ("ბავშვ*", 3), ("ბავშვთა", 3), ("სათამაშო*", 3),
        ("kids", 3), ("baby", 3), ("toddler", 3), ("pampers", 3),
        ("პამპერს*", 3), ("ახალშობილ*", 3), ("მოსწავლ*", 2),
    ],
    PERFUME: [
        ("პარფიუმ*", 4), ("parfum", 4), ("perfume", 4), ("სუნამო*", 4),
        ("fragrance", 3), ("eau de", 3), ("არომატ*", 1),
    ],
    HEALTH_BEAUTY: [
        ("სილამაზ*", 4), ("აფთიაქ*", 4), ("კლინიკ*", 4), ("სტომატოლოგ*", 4),
        ("კოსმეტიკ*", 3), ("cosmetic*", 3), ("beauty", 3), ("pharmacy", 3),
        ("dental", 3), ("clinic", 3), ("სამედიცინო", 3), ("medical", 3),
        ("ჯანმრთელობ*", 3), ("ოპტიკ*", 3), ("optic*", 3), ("სალონ*", 3),
        ("salon", 3), ("spa", 2), ("სპა", 2), ("fitness", 3), ("ფიტნეს*", 3),
        ("gym", 3), ("pilates", 3), ("პილატეს*", 3), ("yoga", 3),
        ("იოგა", 3), ("თმის", 2), ("hair", 2), ("ნეილ*", 2), ("nails", 2),
        ("მასაჟ*", 3), ("massage", 3), ("ვიტამინ*", 2),
    ],
    ACCESSORIES: [
        ("აქსესუარ*", 4), ("accessor*", 4), ("სამკაულ*", 4), ("jewel*", 4),
        ("საათებ*", 3), ("ჩანთ*", 3), ("bag", 2), ("სათვალ*", 3),
        ("sunglass*", 3), ("ბიჟუტერი*", 3), ("ჩემოდან*", 3),
    ],
    CLOTHING: [
        ("ტანსაცმ*", 4), ("clothing", 4), ("apparel", 4), ("ფეხსაცმ*", 4),
        ("shoes", 3), ("footwear", 3), ("ჯინს*", 3), ("jeans", 3),
        ("ბუტიკ*", 3), ("boutique", 3), ("fashion", 2), ("პერანგ*", 3),
        ("ქურთუკ*", 3), ("თეთრეულ*", 2), ("underwear", 3),
        ("სპორტული ტანსაცმ", 4), ("კოლექცი*", 1),
    ],
    ELECTRONICS: [
        ("ტექნიკ*", 4), ("ელექტრონიქ*", 4), ("electronics", 4),
        ("appliance*", 3), ("ტელევიზორ*", 4), ("smartphone*", 3),
        ("ტელეფონ*", 3), ("laptop", 3), ("ლეპტოპ*", 3), ("კომპიუტერ*", 3),
        ("computer", 3), ("iphone", 3), ("samsung", 2), ("xiaomi", 2),
        ("გაჯეტ*", 3), ("gadget*", 3), ("playstation", 3),
        ("საყოფაცხოვრებო ტექნიკ", 4), ("ყურსასმენ*", 3),
    ],
    HOME: [
        ("ავეჯ*", 4), ("furniture", 4), ("ინტერიერ*", 3), ("interior", 3),
        ("სამზარეულო", 3), ("kitchen", 3), ("ჭურჭელ*", 3), ("ხალიჩ*", 3),
        ("carpet", 3), ("კერამიკ*", 3), ("კაფელ*", 3), ("სანტექნიკ*", 4),
        ("რემონტ*", 3), ("tile*", 2), ("განათებ*", 3), ("lighting", 3),
        ("მატრას*", 3), ("ლეიბ*", 3), ("პარკეტ*", 3), ("დეკორ*", 2),
        ("საოჯახო", 3), ("ტექსტილ*", 2),
    ],
    AUTO: [
        ("ავტოსერვის*", 4), ("ავტონაწილ*", 4), ("ავტოსალონ*", 4),
        ("ავტომობილ*", 4), ("საწვავ*", 4), ("fuel", 3), ("საბურავ*", 4),
        ("tire*", 3), ("სამრეცხაო", 4), ("car wash", 4), ("socar", 4),
        ("wissol", 4), ("rompetrol", 4), ("ზეთის შეცვლ", 4), ("ავტო", 2),
    ],
    TRANSPORT: [
        ("ტრანსპორტ*", 4), ("ტაქსი", 4), ("taxi", 4), ("bolt", 3),
        ("yandex go", 4), ("მგზავრობ*", 4), ("მეტრო", 3), ("metro", 3),
        ("სამარშრუტო", 4), ("ავტობუს*", 4), ("scooter", 2), ("სკუტერ*", 2),
    ],
    FOOD_SERVICE: [
        ("რესტორან*", 4), ("restaurant", 4), ("კაფე", 4), ("cafe", 4),
        ("ყავა", 3), ("coffee", 3), ("პიცერი*", 4), ("pizza", 3),
        ("burger", 3), ("ბურგერ*", 3), ("sushi", 3), ("სუში", 3),
        ("mcdonald*", 4), ("bakery", 3), ("საცხობ*", 3), ("საკონდიტრო", 4),
        ("ლანჩ*", 3), ("სადილ*", 2), ("ვახშ*", 2), ("food court", 3),
        ("გემრიელ*", 1),
    ],
    GROCERY: [
        ("სუპერმარკეტ*", 4), ("supermarket", 4), ("სასურსათო", 4),
        ("grocery", 4), ("carrefour", 4), ("spar", 3), ("nikora", 4),
        ("ნიკორა", 4), ("goodwill", 4), ("გუდვილ*", 4), ("agrohub", 4),
        ("ბაზრობ*", 3), ("პროდუქტებ*", 2), ("ღვინ*", 3), ("wine", 3),
        ("ალკოჰოლ*", 3), ("ლუდი", 3),
    ],
    FLOWERS: [
        ("ყვავილ*", 4), ("flower*", 4), ("ბუკეტ*", 4), ("bouquet", 4),
        ("florist", 4),
    ],
    FUN: [
        ("კინო", 4), ("cinema", 4), ("თეატრ*", 4), ("theatre", 4),
        ("კონცერტ*", 4), ("concert", 4), ("ბოულინგ*", 4), ("bowling", 4),
        ("ატრაქციონ*", 4), ("ბატუტ*", 4), ("trampoline", 4),
        ("გასართობ*", 4), ("entertainment", 3), ("კვესტ*", 3),
        ("ბილეთ*", 2), ("festival", 3), ("ფესტივალ*", 3), ("საბაგირო", 3),
    ],
    LEISURE: [
        ("სასტუმრო", 4), ("hotel", 4), ("resort", 4), ("კურორტ*", 4),
        ("აუზ*", 3), ("ბანაკ*", 3), ("camping", 3), ("პლაჟ*", 3),
        ("beach", 3), ("დასასვენებელ*", 4), ("ღამისთევ*", 4),
        ("ქოთეჯ*", 3), ("cottage", 3), ("გუდაურ*", 2), ("ბაკურიან*", 2),
    ],
    TRAVEL: [
        ("მოგზაურ*", 4), ("travel", 4), ("ავიაბილეთ*", 4), ("flight", 3),
        ("ავიაკომპან*", 4), ("airline*", 4), ("ტურისტულ*", 4),
        ("ტურპაკეტ*", 4), ("booking.com", 4), ("wizz", 4),
        ("turkish airlines", 4), ("აეროპორტ*", 3), ("lounge", 3),
        ("სავიზო", 3), ("esim", 3),
    ],
    EDUCATION: [
        ("განათლებ*", 4), ("education", 4), ("სკოლ*", 3), ("school", 3),
        ("უნივერსიტეტ*", 4), ("university", 4), ("კურს*", 3),
        ("course*", 3), ("ტრენინგ*", 3), ("training", 3), ("აკადემი*", 3),
        ("სასწავლო", 4), ("ენის შესწავლ", 4), ("ლექცი*", 3),
    ],
    DEVELOPERS: [
        ("დეველოპერ*", 4), ("developer*", 4), ("უძრავი ქონებ", 4),
        ("real estate", 4), ("საცხოვრებელი კომპლექს", 4), ("residence", 3),
        ("ბინის შეძენ", 4), ("ბინები", 4), ("apartment*", 3),
    ],
    SHOPPING: [
        ("სავაჭრო ცენტრ", 4), ("shopping mall", 4), ("მოლი", 3),
        ("mall", 3), ("outlet", 3), ("უნივერმაღ*", 4),
        ("department store", 4), ("საჩუქრებ*", 1),
    ],
    ONLINE: [
        ("ონლაინ მაღაზი", 4), ("online store", 4), ("ecommerce", 3),
        ("e-commerce", 3), ("მარკეტფლეის*", 4), ("marketplace", 3),
        ("wolt", 4), ("glovo", 4), ("amazon", 3), ("aliexpress", 3),
    ],
}

# Veto rules: if any of these match, the category is disqualified no matter
# how it scored. This is what stops one ambiguous word dragging an offer
# into the wrong bucket.
VETO_RULES = {
    TRANSPORT: ["მეტრომარტ*", "metromart*"],   # a shop, not the subway
    GROCERY: ["smart*", "სმარტ*"],             # "smart" TV is not a market
    DEVELOPERS: ["კაბინეტ*"],
    AUTO: ["ავტორ*", "ავტომატურ*"],            # author / automatic
}

# Field weights — a brand name is worth far more than a passing mention
# buried in marketing copy.
FIELD_WEIGHTS = {"brand": 5, "title": 3, "description": 1}

# Below this the guess isn't worth making; the offer stays "სხვა" and shows
# up in the audit report for a human to look at.
MIN_SCORE = 4


# =========================================================================
# Matching machinery
# =========================================================================

_WORD_RE = re.compile(r"[0-9a-zა-ჰ]+")
_PUNCT_RE = re.compile(r"[^\w\sა-ჰ.]", re.UNICODE)


def normalize_brand(name) -> str:
    """Lowercase, drop punctuation, collapse whitespace, drop .ge / .com / .ჯი."""
    if not name:
        return ""
    text = str(name).lower().strip()
    text = re.sub(r"\.(com|ge|ჯი)\b", "", text)
    text = _PUNCT_RE.sub(" ", text).replace(".", " ")
    return re.sub(r"\s+", " ", text).strip()


BRAND_CATEGORIES.update(
    {normalize_brand(k): v for k, v in _RAW_BRAND_CATEGORIES.items()}
)


def lookup_brand(brand_key: str):
    """
    Brand lookup that tolerates Georgian nominative endings.

    Stripping ".ჯი" off "მინილენდ.ჯი" leaves "მინილენდ", but the bricks-
    and-mortar entry is filed as "მინილენდი". Trying the key with and
    without a trailing "ი" links the online and offline arms of the same
    merchant without duplicating every row.
    """
    if not brand_key:
        return None
    if brand_key in BRAND_CATEGORIES:
        return BRAND_CATEGORIES[brand_key]
    if BRAND_CATEGORIES.get(brand_key + "ი"):
        return BRAND_CATEGORIES[brand_key + "ი"]
    if brand_key.endswith("ი") and brand_key[:-1] in BRAND_CATEGORIES:
        return BRAND_CATEGORIES[brand_key[:-1]]
    return None


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _brand_in_text(text: str):
    """
    Finds a known merchant mentioned inside a title or description.

    Georgian inflects merchant names ("მეტრომარტში", "ალტაში"), so this
    matches on stem rather than equality, and prefers the longest match so
    "ველი სთორი" beats a stray "ველი". Only used for bank-product offers,
    where the brand field holds a payment product instead of a shop.
    """
    if not text:
        return None
    tokens = _tokens(text)
    best_key, best_len = None, 0
    for key in BRAND_CATEGORIES:
        if " " in key:
            if key in text.lower() and len(key) > best_len:
                best_key, best_len = key, len(key)
            continue
        stem = key[:-1] if key.endswith("ი") and len(key) > 4 else key
        if len(stem) < 4:
            continue
        if any(tok.startswith(stem) for tok in tokens) and len(stem) > best_len:
            best_key, best_len = key, len(stem)
    return BRAND_CATEGORIES.get(best_key) if best_key else None


def _pattern_hits(pattern: str, text: str, tokens: list[str]) -> bool:
    """
    Three pattern flavours:
      "foo bar"  phrase  -> substring match on the raw text
      "foo*"     prefix  -> any token starting with "foo"
      "foo"      exact   -> a token equal to "foo"
    """
    pattern = pattern.lower()
    if " " in pattern:
        return pattern in text
    if pattern.endswith("*"):
        stem = pattern[:-1]
        return any(tok.startswith(stem) for tok in tokens)
    return pattern in tokens


def _is_vetoed(category: str, text: str, tokens: list[str]) -> bool:
    return any(_pattern_hits(p, text, tokens) for p in VETO_RULES.get(category, []))


def score_categories(offer: dict) -> dict[str, int]:
    """Scores every category. Exposed so the audit report can show runners-up."""
    fields = {
        "brand": (offer.get("brand") or "").lower(),
        "title": (offer.get("title") or "").lower(),
        "description": (offer.get("description") or "").lower(),
    }
    tokenized = {name: _tokens(val) for name, val in fields.items()}
    combined_text = " ".join(fields.values())
    combined_tokens = _tokens(combined_text)

    scores: dict[str, int] = {}
    for category, rules in KEYWORD_RULES.items():
        if _is_vetoed(category, combined_text, combined_tokens):
            continue
        total = 0
        for pattern, weight in rules:
            for field_name, field_weight in FIELD_WEIGHTS.items():
                if _pattern_hits(pattern, fields[field_name], tokenized[field_name]):
                    total += weight * field_weight
        if total:
            scores[category] = total
    return scores


# =========================================================================
# Layer 1 — manual overrides
# =========================================================================

_overrides_cache = None
_category_map_cache = None


def load_category_map() -> dict:
    """
    {offer_slug: [category, ...]} as scraped from TBC's own filters.

    Returns {} when the file is missing, which is the normal state until
    html_categories.py has been run — everything then falls through to the
    brand dictionary and keyword layer exactly as before.
    """
    global _category_map_cache
    if _category_map_cache is not None:
        return _category_map_cache
    if not os.path.exists(CATEGORY_MAP_FILE):
        _category_map_cache = {}
        return _category_map_cache
    try:
        with open(CATEGORY_MAP_FILE, "r", encoding="utf-8") as f:
            _category_map_cache = json.load(f).get("categories", {})
    except (json.JSONDecodeError, OSError) as e:
        print(f"[categorize] Ignoring unreadable category map: {e}")
        _category_map_cache = {}
    return _category_map_cache


def load_overrides() -> dict:
    """
    data/category_overrides.json maps either an offer slug or a brand name
    to a category:

        {
          "by_slug":  {"metromart-ganatsileba": "ტექნიკა"},
          "by_brand": {"მეტრომარტი": "ტექნიკა"}
        }

    Anything in here wins outright. This is the escape hatch for the team:
    spot a wrong category on the dashboard, add one line, done.
    """
    global _overrides_cache
    if _overrides_cache is not None:
        return _overrides_cache
    if not os.path.exists(OVERRIDES_FILE):
        _overrides_cache = {"by_slug": {}, "by_brand": {}}
        return _overrides_cache
    try:
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _overrides_cache = {
            "by_slug": raw.get("by_slug", {}),
            "by_brand": {
                normalize_brand(k): v for k, v in raw.get("by_brand", {}).items()
            },
        }
    except (json.JSONDecodeError, OSError) as e:
        print(f"[categorize] Ignoring unreadable overrides file: {e}")
        _overrides_cache = {"by_slug": {}, "by_brand": {}}
    return _overrides_cache


# =========================================================================
# Channel — online vs in-store
# =========================================================================
# TBC folds online merchants into "ონლაინ პარტნიორები", which throws away
# what the merchant actually sells: ოკაიდი.ჯი and ოკაიდი become different
# categories despite being the same business. We keep the product category
# and record the channel separately, so you can slice either way.

_ONLINE_BRAND_RE = re.compile(r"\.(ge|ჯი)\s*$", re.IGNORECASE)
_ONLINE_HINTS = ["ონლაინ", "online", "www", "ვებგვერდ", "აპლიკაცი"]
_STORE_HINTS = ["მაღაზია", "ფილიალ", "სავაჭრო ობიექტ", "ობიექტებ"]


def detect_channel(offer: dict) -> str:
    """Returns 'online', 'instore', or 'both'."""
    brand = (offer.get("brand") or "").strip()
    if _ONLINE_BRAND_RE.search(brand):
        return "online"
    text = f"{offer.get('title') or ''} {offer.get('description') or ''}".lower()
    online_hint = any(h in text for h in _ONLINE_HINTS)
    store_hint = any(h in text for h in _STORE_HINTS)
    if online_hint and store_hint:
        return "both"
    if online_hint:
        return "online"
    return "instore"


# =========================================================================
# Bank-product offers
# =========================================================================
# ~26 offers are branded "განაწილება" / "განვადება" / "თიბისი" /
# "Mastercard" — TBC's own payment products, not merchant partnerships.
# Counting them as merchant deals inflates every category share, so they
# get flagged and can be filtered out of competitive analysis.

BANK_PRODUCT_BRANDS = {
    "განაწილება": "განაწილება",
    "განვადება": "განვადება",
    "თიბისი": "თიბისი",
    "mastercard": "Mastercard",
    "visa": "Visa",
    "თიბისი ბარათი": "თიბისი ბარათი",
    "tbc დაზღვევა": "თიბისი დაზღვევა",
    "თიბისი კონცეპტის საკოლექციო მაღაზია": "თიბისი კონცეპტი",
}


def detect_bank_product(offer: dict):
    """Returns the product name if this is a TBC product promo, else None."""
    return BANK_PRODUCT_BRANDS.get(normalize_brand(offer.get("brand")))


# =========================================================================
# Public API
# =========================================================================

def classify(offer: dict, api_categories: list[str] | None = None) -> dict:
    """
    Full classification for one offer.

    Returns:
      category             the winning TBC category
      category_source      override | api | brand | keywords | fallback
      category_confidence  high | medium | low
      alt_categories       runners-up, for auditing borderline calls
      channel              online | instore | both
      bank_product         product name, or None for merchant offers
    """
    overrides = load_overrides()
    brand_key = normalize_brand(offer.get("brand"))
    result = {
        "channel": detect_channel(offer),
        "bank_product": detect_bank_product(offer),
        "alt_categories": [],
    }

    # 1. manual override
    slug = offer.get("slug")
    if slug and slug in overrides["by_slug"]:
        return {**result, "category": overrides["by_slug"][slug],
                "category_source": "override", "category_confidence": "high"}
    if brand_key and brand_key in overrides["by_brand"]:
        return {**result, "category": overrides["by_brand"][brand_key],
                "category_source": "override", "category_confidence": "high"}

    # 2a. TBC's own tag from the scraped listing. Beats anything we infer,
    # because it is their categorisation rather than a guess about it.
    if not api_categories and slug:
        scraped = load_category_map().get(slug)
        if scraped:
            api_categories = scraped

    # 2b. TBC's own tag, however we obtained it
    if api_categories:
        return {**result, "category": api_categories[0],
                "category_source": "api", "category_confidence": "high",
                "alt_categories": list(api_categories[1:])}

    # 3. curated merchant dictionary
    hit = lookup_brand(brand_key)
    if hit:
        return {**result, "category": hit,
                "category_source": "brand", "category_confidence": "high"}

    # 3b. Bank-product offers ("განაწილება", "თიბისი", ...) carry the real
    # merchant in the title instead of the brand field, e.g. brand
    # "თიბისი" / title "მეტრომარტი". Look for a known merchant there.
    if result["bank_product"]:
        hit = _brand_in_text(offer.get("title") or "")
        if hit:
            return {**result, "category": hit,
                    "category_source": "brand", "category_confidence": "medium"}

    # 4. weighted keyword scoring
    scores = score_categories(offer)
    if scores:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_category, best_score = ranked[0]
        if best_score >= MIN_SCORE:
            runner_up = ranked[1][1] if len(ranked) > 1 else 0
            confident = best_score >= 9 and best_score >= runner_up * 2
            return {**result, "category": best_category,
                    "category_source": "keywords",
                    "category_confidence": "high" if confident else "medium",
                    "alt_categories": [c for c, _ in ranked[1:3]]}

    # 5. nothing stuck
    return {**result, "category": OTHER, "category_source": "fallback",
            "category_confidence": "low"}


def categorize(offer: dict, api_categories: list[str] | None = None) -> str:
    """Backwards-compatible shim: just the category string."""
    return classify(offer, api_categories)["category"]


# --- Cashback / cap extraction -------------------------------------------
# Parses TBC's Georgian offer copy. Typical phrasings:
#   "დაიბრუნეთ 30% ულიმიტოდ და მომენტალურად"
#   "დაიბრუნე 20%, მაქს. 200₾"
#   "0%-იანი განვადება ... ეფექტური 4.3%"   <- must NOT read as cashback

_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
_UNLIMITED_RE = re.compile(r"ულიმიტ")
_CAP_AMOUNT_RE = re.compile(
    r"(?:მაქს[.იმუმ]*|არაუმეტეს|ლიმიტი|დაიბრუნე)\s*"
    r"(\d[\d\s]{0,7}(?:[.,]\d{1,2})?)\s*(?:₾|ლარ)"
)
_ANY_AMOUNT_RE = re.compile(r"(\d[\d\s]{0,7}(?:[.,]\d{1,2})?)\s*(?:₾|ლარ)")

# Percentages next to these words are interest rates or instalment terms,
# not a customer benefit.
_RATE_CONTEXT = ["ეფექტურ", "საპროცენტო", "წლიური"]


def extract_offer_economics(offer: dict) -> dict:
    """
    Returns cashback_percent, cap_unlimited, cap_amount, and offer_type
    ('cashback' | 'discount' | 'installment' | 'other').

    Best-effort: TBC's copy is free text, so treat these as indicative
    rather than contractual.
    """
    haystack = f"{offer.get('title') or ''} {offer.get('description') or ''}"
    lowered = haystack.lower()

    candidates = []
    for match in _PERCENT_RE.finditer(haystack):
        value = int(match.group(1))
        if not 0 < value <= 100:
            continue
        # Look at the 30 characters before the number: if it's framed as a
        # rate, it isn't a customer benefit.
        context = lowered[max(0, match.start() - 30):match.start()]
        if any(word in context for word in _RATE_CONTEXT):
            continue
        candidates.append(value)

    cashback_percent = max(candidates) if candidates else None
    cap_unlimited = bool(_UNLIMITED_RE.search(haystack))

    cap_amount = None
    if not cap_unlimited:
        match = _CAP_AMOUNT_RE.search(haystack) or _ANY_AMOUNT_RE.search(haystack)
        if match:
            raw = match.group(1).replace(" ", "").replace(",", ".")
            try:
                cap_amount = float(raw)
            except ValueError:
                cap_amount = None

    if "ქეშბექ" in lowered or "დაიბრუნ" in lowered:
        offer_type = "cashback"
    elif "განვადებ" in lowered or "განაწილებ" in lowered:
        offer_type = "installment"
    elif "ფასდაკლებ" in lowered or "discount" in lowered:
        offer_type = "discount"
    else:
        offer_type = "other"

    return {
        "cashback_percent": cashback_percent,
        "cap_unlimited": cap_unlimited,
        "cap_amount": cap_amount,
        "offer_type": offer_type,
    }
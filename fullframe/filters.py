"""Keep non-news out: shopping deals, product buying guides, food/restaurant reviews, recipes,
horoscopes, puzzles, lottery numbers, sponsored posts and newsletter round-ups.

Movie, TV, book, music and arts reviews and other cultural coverage are deliberately NOT filtered.
Add your own patterns under "filters" in config.json (regular expressions, case-insensitive).
"""
import re

# Section paths that only ever hold commerce / lifestyle-service content
URL_PATTERNS = [
    r"/shopping/", r"/deals?/", r"/coupons?/", r"/commerce/", r"/shop/", r"/buying-guides?",
    r"/gift-guides?", r"/product-reviews?/", r"/reviewed/", r"/underscored/", r"/select/",
    r"/essentials/", r"/thefilter/", r"/recommended/", r"/indybest/", r"/gma/deals", r"/best-products",
    r"/sponsored/", r"/partner-content/", r"/paid-?(post|content)", r"/brandstudio/",
    r"/recipes?/", r"/food/", r"/dining/", r"/restaurants?/", r"/food-and-drink/", r"/food-drink/",
    r"/horoscopes?", r"/astrology/", r"/puzzles?/", r"/crosswords?/", r"/games/", r"/wordle",
    r"/lottery/", r"/lotto/",
]

# Headline patterns. Written narrowly so real news ("trade deal", "Black Friday spending falls") survives.
TITLE_PATTERNS = [
    # shopping and deals
    r"\b(black friday|cyber monday|cyber week|prime day|boxing day|labor day|memorial day|presidents' day)\b.{0,40}\b(deals?|discounts?|bargains?|offers?|coupons?|doorbusters?|shop|buy now)\b",
    r"\b(best|early|top|biggest|last-minute)\b.{0,25}\b(black friday|cyber monday|prime day|boxing day)\b",
    r"\bbest\b.{0,40}\bdeals?\b", r"\bdeals? (of the day|of the week|you can (shop|get|buy)|to shop)\b", r"\bdeal alert\b",
    r"\bbonus bets?\b", r"\b(sportsbook|betting|casino) (promo|bonus|offer)\b",
    r"\b(save|get)\b.{0,15}(\$\d|£\d|€\d|\d+% off)", r"\d+% off\b", r"\bon sale (now|for|at)\b", r"\b(promo|discount|coupon) codes?\b",
    r"\bunder \$\d+\b", r"\bgift (guide|ideas)\b", r"\bgifts? for (him|her|men|women|kids|dad|mom|mum|everyone|the)\b",
    r"\bstocking stuffers?\b", r"\bbuying guide\b", r"\b(we|i) tested\b", r"\btested (and|&) reviewed\b",
    r"\bbest\b.{0,40}\b(to buy|money can buy|you can buy|for the money|of 20\d\d)\b", r"\bwhere to buy\b",
    r"\bshop (the|our|now)\b", r"\b(amazon|walmart|target|costco|best buy)\b.{0,30}\b(deals?|sale|discounts?)\b",
    r"\bsponsored\b", r"\bpaid (post|content|partnership)\b", r"\badvertorial\b",
    # food reviews, recipes
    r"\brecipes?\b", r"\b(restaurant|dining|food|wine|menu) review\b", r"\breview:.{0,40}\b(restaurant|bistro|cafe|café|brasserie|tavern|steakhouse|eatery)\b",
    r"\bwhere to eat\b", r"\bbest (restaurants?|pizza|burgers?|bagels?|brunch|tacos|steak(house)?s?|coffee shops?|bakeries|bars)\b",
    r"\btaste test\b", r"\b(we|i) tried\b.{0,40}\b(menu|burger|sandwich|pizza|meal|drink|snack|recipe)\b",
    r"\bfast[- ]food\b.{0,30}\branked\b", r"\branked\b.{0,30}\b(snacks?|cereals?|burgers?|candy|chips)\b",
    # puzzles, horoscopes, lottery
    r"\bhoroscopes?\b", r"\bastrology\b", r"\bwordle\b", r"\bconnections (hints?|answers?)\b", r"\bstrands (hints?|answers?)\b",
    r"\bcrosswords?\b", r"\bsudoku\b", r"^quiz\b", r"\bquiz:", r"\bwinning numbers\b",
    r"\b(powerball|mega millions|lotto|euromillions|lottery) (numbers|results|drawing)\b",
    # newsletter round-ups (they bundle many stories and pollute grouping)
    r"\byour (morning|evening|daily|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday) briefing\b",
    r"^(morning|evening|daily) (briefing|digest|rundown)\b",
]


class ContentFilter:
    def __init__(self, cfg=None):
        f = (cfg or {}).get("filters", {}) or {}
        self.enabled = f.get("enabled", True)
        urls = URL_PATTERNS + list(f.get("extra_url_patterns", []))
        titles = TITLE_PATTERNS + list(f.get("extra_title_patterns", []))
        self.url_re = re.compile("|".join("(?:%s)" % p for p in urls), re.I)
        self.title_re = re.compile("|".join("(?:%s)" % p for p in titles), re.I)
        allow = list(f.get("allow_title_patterns", []))
        self.allow_re = re.compile("|".join("(?:%s)" % p for p in allow), re.I) if allow else None

    def blocked(self, title, url=""):
        """Return a short reason if the article isn't news we want, else None."""
        if not self.enabled:
            return None
        title = title or ""
        if self.allow_re and self.allow_re.search(title):
            return None
        if url and "news.google.com" not in url:
            path = re.sub(r"^https?://[^/]+", "", url.lower())
            m = self.url_re.search(path)
            if m:
                return "url:" + m.group(0)
        m = self.title_re.search(title)
        if m:
            return "title:" + m.group(0)[:40]
        return None

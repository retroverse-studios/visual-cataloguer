"""Price research providers.

Providers estimate the market value of an item from recent sales data and
return a normalised PriceEstimate. The first (and default) provider scrapes
eBay's public sold/completed-listings search. This is personal-use scraping
of a public page — keep request volume low (it is only invoked on demand,
one search per item) and never authenticate: sold results are public, and
using a real account would put that account at risk.

The HTML parsing is deliberately isolated in _EbayCardParser so that when
eBay changes markup, the fix is confined to one class with a saved-HTML
test fixture (tests/fixtures/ebay_sold_search.html).
"""

from __future__ import annotations

import re
import statistics
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser

import httpx

# Currency symbol/prefix → ISO code. Ordered longest-prefix first.
_CURRENCY_PREFIXES: list[tuple[str, str]] = [
    ("AU $", "AUD"),
    ("US $", "USD"),
    ("NZ $", "NZD"),
    ("C $", "CAD"),
    ("£", "GBP"),
    ("EUR", "EUR"),
    ("€", "EUR"),
    ("$", ""),  # bare $ — resolved to the site's default currency
]

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Sold 4 Jul 2026" (AU/UK) and "Sold Jul 4, 2026" (US)
_SOLD_DMY = re.compile(r"sold\s+(\d{1,2})\s+([a-z]{3})[a-z]*\.?\s+(\d{4})", re.IGNORECASE)
_SOLD_MDY = re.compile(r"sold\s+([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)

_AMOUNT = re.compile(r"([\d,]+(?:\.\d+)?)")

# eBay pads search results with placeholder promo cards.
_PLACEHOLDER_TITLES = {"shop on ebay"}

# Default currency per eBay site host.
_SITE_CURRENCIES = {
    "www.ebay.com.au": "AUD",
    "www.ebay.com": "USD",
    "www.ebay.co.uk": "GBP",
    "www.ebay.ca": "CAD",
    "www.ebay.ie": "EUR",
    "www.ebay.de": "EUR",
    "www.ebay.fr": "EUR",
    "www.ebay.it": "EUR",
    "www.ebay.es": "EUR",
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}


class PricingError(Exception):
    """Raised when a price lookup fails (network, blocked, or no data)."""


@dataclass
class SoldListing:
    """One sold listing scraped from a search results page."""

    title: str
    price: float
    currency: str
    sold_date: date | None
    url: str | None


@dataclass
class PriceEstimate:
    """Normalised price research result."""

    source: str
    query: str
    search_url: str
    currency: str
    price_low: float
    price_median: float
    price_high: float
    sample_size: int
    most_recent_sale: date | None
    oldest_sale: date | None
    listings: list[SoldListing] = field(default_factory=list)


# ─── HTML parsing ────────────────────────────────────────────────────────────

# Class tokens that mark a capture role, for both eBay markup generations:
# the current "su-*" card layout and the legacy "s-item" layout.
_CARD_TOKENS = {"su-card-container", "s-item"}
_ROLE_TOKENS = {
    "su-item-card__title": "title",
    "s-item__title": "title",
    "su-item-card__price": "price",
    "s-item__price": "price",
    "signal": "sold",
    "signal--recent": "sold",
    "POSITIVE": "sold",
    "s-item__caption--signal": "sold",
}


class _EbayCardParser(HTMLParser):
    """Extract (title, url, price text, sold text) per result card."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self._card: dict[str, str] | None = None
        # Active text capture: (role, tag name, open-tag depth for that tag)
        self._role: str | None = None
        self._role_tag: str = ""
        self._role_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())

        if self._role is not None:
            if tag == self._role_tag:
                self._role_depth += 1
            return

        if classes & _CARD_TOKENS:
            self._card = {}
            self.cards.append(self._card)
            return

        if self._card is None:
            return

        role = next((r for t, r in _ROLE_TOKENS.items() if t in classes), None)
        if role is not None:
            if role == "title" and tag == "a":
                href = attr_map.get("href")
                if href:
                    self._card["url"] = href
            self._role = role
            self._role_tag = tag
            self._role_depth = 1
            self._card.setdefault(role, "")

    def handle_endtag(self, tag: str) -> None:
        if self._role is not None and tag == self._role_tag:
            self._role_depth -= 1
            if self._role_depth <= 0:
                self._role = None

    def handle_data(self, data: str) -> None:
        if self._role is not None and self._card is not None:
            self._card[self._role] = (self._card.get(self._role, "") + data).strip()


def _parse_price(text: str, default_currency: str) -> tuple[float, str] | None:
    """Parse a price string like 'AU $55.98' or '$20.00 to $40.00'.

    Ranges collapse to their first amount.
    """
    stripped = text.strip()
    currency = default_currency
    for prefix, code in _CURRENCY_PREFIXES:
        if stripped.startswith(prefix):
            currency = code or default_currency
            break
    match = _AMOUNT.search(stripped)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "")), currency
    except ValueError:
        return None


def _parse_sold_date(text: str) -> date | None:
    match = _SOLD_DMY.search(text)
    if match:
        day, month_name, year = match.group(1), match.group(2), match.group(3)
    else:
        match = _SOLD_MDY.search(text)
        if not match:
            return None
        month_name, day, year = match.group(1), match.group(2), match.group(3)
    month = _MONTHS.get(month_name.lower())
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def parse_sold_listings(html: str, default_currency: str) -> list[SoldListing]:
    """Parse an eBay sold/completed search results page into listings.

    Placeholder promo cards and cards without a parseable title, price and
    sold date are dropped — requiring the sold date is also what filters out
    non-result cards (ads, "people also searched" modules).
    """
    parser = _EbayCardParser()
    parser.feed(html)

    listings: list[SoldListing] = []
    for card in parser.cards:
        title = card.get("title", "").strip()
        if not title or title.lower() in _PLACEHOLDER_TITLES:
            continue
        sold_date = _parse_sold_date(card.get("sold", ""))
        if sold_date is None:
            continue
        price_text = card.get("price", "")
        parsed = _parse_price(price_text, default_currency)
        if parsed is None:
            continue
        price, currency = parsed
        if price <= 0:
            continue
        listings.append(
            SoldListing(
                title=title,
                price=price,
                currency=currency,
                sold_date=sold_date,
                url=card.get("url"),
            )
        )
    return listings


# ─── Provider ────────────────────────────────────────────────────────────────


class EbaySoldPricingProvider:
    """Estimate prices from eBay's public sold/completed listings search.

    Fetches the site homepage first to pick up session cookies — eBay's edge
    rejects cold hits on /sch/ with 403, but accepts the same request once a
    session cookie is present.
    """

    source = "ebay_sold"

    def __init__(self, site: str = "www.ebay.com.au", timeout: float = 30.0) -> None:
        self.site = site
        self.timeout = timeout
        self.default_currency = _SITE_CURRENCIES.get(site, "USD")

    def search_url(self, keywords: str) -> str:
        params = urllib.parse.urlencode(
            {"_nkw": keywords, "LH_Sold": "1", "LH_Complete": "1", "_ipg": "60"}
        )
        return f"https://{self.site}/sch/i.html?{params}"

    def _fetch(self, url: str) -> str:
        with httpx.Client(
            headers=_BROWSER_HEADERS, timeout=self.timeout, follow_redirects=True
        ) as client:
            try:
                client.get(f"https://{self.site}/")  # cookie warm-up
                response = client.get(url, headers={"Referer": f"https://{self.site}/"})
            except httpx.HTTPError as e:
                raise PricingError(f"Could not reach eBay: {e}") from e
        if response.status_code != 200:
            raise PricingError(
                f"eBay returned HTTP {response.status_code} — likely bot detection. "
                "Wait a few minutes and try again."
            )
        return response.text

    def research(self, keywords: str) -> PriceEstimate:
        """Search sold listings for the keywords and summarise prices."""
        url = self.search_url(keywords)
        html = self._fetch(url)
        listings = parse_sold_listings(html, self.default_currency)
        if not listings:
            # eBay occasionally serves a stripped page to a brand-new session;
            # a second attempt with fresh cookies usually gets real results.
            time.sleep(2)
            html = self._fetch(url)
            listings = parse_sold_listings(html, self.default_currency)
        if not listings:
            lowered = html.lower()
            if "captcha" in lowered or "challenge" in lowered:
                raise PricingError(
                    "eBay served a bot challenge instead of results. "
                    "Wait a few minutes and try again."
                )
            raise PricingError(f"No sold listings found for: {keywords}")

        # Summarise in the majority currency only, so a stray US-dollar
        # listing on ebay.com.au doesn't corrupt the range.
        by_currency: dict[str, list[SoldListing]] = {}
        for listing in listings:
            by_currency.setdefault(listing.currency, []).append(listing)
        currency, sample = max(by_currency.items(), key=lambda kv: len(kv[1]))

        prices = [listing.price for listing in sample]
        dates = [listing.sold_date for listing in sample if listing.sold_date]
        return PriceEstimate(
            source=self.source,
            query=keywords,
            search_url=url,
            currency=currency,
            price_low=min(prices),
            price_median=round(statistics.median(prices), 2),
            price_high=max(prices),
            sample_size=len(sample),
            most_recent_sale=max(dates) if dates else None,
            oldest_sale=min(dates) if dates else None,
            listings=sample,
        )


def build_search_keywords(
    title: str | None, platform: str | None, ocr_text: str | None = None
) -> str:
    """Build search keywords from item fields.

    Uses the effective title plus the platform (unless the title already
    mentions it). Falls back to the first line of OCR text when no title
    is known.
    """
    keywords = (title or "").strip()
    if not keywords and ocr_text:
        keywords = ocr_text.strip().splitlines()[0].strip()
    if not keywords:
        return ""
    platform = (platform or "").strip()
    if platform and platform.lower() not in keywords.lower():
        keywords = f"{keywords} {platform}"
    return keywords

"""Pure parsing helpers for Amazon product pages (no network access)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from .errors import BlockedError, InvalidUrlError, ParseError
from .formatting import parse_price

AMAZON_DOMAIN = "amazon.de"
URL_RE = re.compile(r"https?://\S+")
_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?:[/?#]|$)")

_CAPTCHA_MARKERS = ("api-services-support@amazon.com", "/errors/validateCaptcha", "Robot Check")
_CAPTCHA_MAX_LENGTH = 100_000  # a real product page is >1 MB, challenge pages are tiny

# Containers that hold the price of the *main* offer. Prices anywhere else on the
# page (carousels, "frequently bought together", ads) must never be used.
_CORE_CONTAINERS = (
    "#corePriceDisplay_desktop_feature_div",
    "#corePrice_feature_div",
    "#apex_desktop",
)
_BUYBOX_CONTAINERS = ("#desktop_buybox", "#buybox", "#rightCol")
_PRICE_TO_PAY = ".priceToPay .a-offscreen, .apexPriceToPay .a-offscreen, #price_inside_buybox"
_ANY_PRICE = ".a-price .a-offscreen"
_HIDDEN_PRICE_FIELDS = ("#twister-plus-price-data-price", "#attach-base-product-price")

_UNAVAILABLE_MARKERS = (
    "currently unavailable",
    "no featured offers available",
    "derzeit nicht verfügbar",
    "aktuell nicht verfügbar",
    "keine hervorgehobenen angebote",
)
_ADD_TO_CART = "#add-to-cart-button, input[name='submit.add-to-cart']"
_AVAILABILITY_BLOCKS = "#availability, #outOfStock, #outOfStockBuyBox_feature_div, #buybox"


@dataclass(frozen=True)
class ProductSnapshot:
    """What we know about a product at one point in time."""

    asin: str
    title: str
    price: float | None  # None -> currently unavailable


def normalize_product_url(text: str) -> tuple[str, str]:
    """Find a product link in ``text`` and return ``(canonical_url, asin)``.

    Tracking parameters and the localized slug are dropped, so the same product
    always maps to the same URL.
    """
    match = URL_RE.search(text)
    if match is None:
        raise InvalidUrlError("I couldn't find a link in your message.")

    parsed = urlparse(match.group())
    host = (parsed.hostname or "").lower()
    if host != AMAZON_DOMAIN and not host.endswith(f".{AMAZON_DOMAIN}"):
        raise InvalidUrlError(f"Only {AMAZON_DOMAIN} product links are supported.")

    asin_match = _ASIN_RE.search(parsed.path)
    if asin_match is None:
        raise InvalidUrlError("That doesn't look like a product page (no /dp/ASIN in the link).")

    asin = asin_match.group(1).upper()
    return f"https://www.{AMAZON_DOMAIN}/dp/{asin}", asin


def parse_product_page(html: str, asin: str) -> ProductSnapshot:
    """Extract title and buy-box price from a product page.

    Raises:
        BlockedError: the page is a CAPTCHA challenge.
        ParseError: no price was found and the page does not say the product is unavailable.
    """
    if _is_captcha(html):
        raise BlockedError("Amazon asked for a CAPTCHA. Please try again in a few minutes.")

    soup = BeautifulSoup(html, "html.parser")
    price = _extract_price(soup)
    if price is None and not _is_unavailable(soup):
        raise ParseError(_no_price_message(soup))
    return ProductSnapshot(asin=asin, title=_extract_title(soup, asin), price=price)


def _no_price_message(soup: BeautifulSoup) -> str:
    """Explain a missing price; mention the delivery country when Amazon shows one.

    Amazon hides prices of many products when the page is requested from a region
    it does not deliver to, which looks exactly like an unsupported layout.
    """
    message = "I couldn't read the price from this page."
    location = _delivery_location(soup)
    if location:
        message += (
            f" Amazon is showing the page for delivery to \u201c{location}\u201d, and it often hides prices"
            " for regions it does not serve."
        )
    return message + " Otherwise the product may use a page layout I don't support yet."


def _delivery_location(soup: BeautifulSoup) -> str | None:
    element = soup.select_one("#glow-ingress-line2")
    if element is None:
        return None
    text = " ".join(element.get_text().split())
    return text or None


def _is_captcha(html: str) -> bool:
    return len(html) < _CAPTCHA_MAX_LENGTH and any(marker in html for marker in _CAPTCHA_MARKERS)


def _extract_title(soup: BeautifulSoup, asin: str) -> str:
    element = soup.select_one("#productTitle")
    if element is not None and element.get_text(strip=True):
        return " ".join(element.get_text().split())
    if soup.title is not None and soup.title.get_text(strip=True):
        return " ".join(soup.title.get_text().split())
    return f"Amazon product {asin}"


def _extract_price(soup: BeautifulSoup) -> float | None:
    """Return the price of the main offer, or None. Never guesses from unrelated blocks."""
    lookups = (
        (_CORE_CONTAINERS, _PRICE_TO_PAY),
        (_BUYBOX_CONTAINERS, _PRICE_TO_PAY),
        (_CORE_CONTAINERS, _ANY_PRICE),
    )
    for containers, selector in lookups:
        price = _first_price_in(soup, containers, selector)
        if price is not None:
            return price
    return _hidden_field_price(soup)


def _first_price_in(soup: BeautifulSoup, containers: tuple[str, ...], selector: str) -> float | None:
    for container_selector in containers:
        for container in soup.select(container_selector):
            for element in container.select(selector):
                if _is_reference_price(element):
                    continue
                price = parse_price(element.get_text())
                if price is not None:
                    return price
    return None


def _is_reference_price(element: Tag) -> bool:
    """True for struck-through list prices and per-unit prices ("€3.89 / 100 g")."""
    return (
        element.find_parent(attrs={"data-a-strike": "true"}) is not None
        or element.find_parent(class_=["basisPrice", "pricePerUnit"]) is not None
    )


def _hidden_field_price(soup: BeautifulSoup) -> float | None:
    for selector in _HIDDEN_PRICE_FIELDS:
        element = soup.select_one(selector)
        if element is not None:
            price = parse_price(str(element.get("value") or ""))
            if price is not None:
                return price
    return None


def _is_unavailable(soup: BeautifulSoup) -> bool:
    if soup.select_one(_ADD_TO_CART) is not None:
        return False
    for block in soup.select(_AVAILABILITY_BLOCKS):
        text = block.get_text(" ", strip=True).lower()
        if any(marker in text for marker in _UNAVAILABLE_MARKERS):
            return True
    return False

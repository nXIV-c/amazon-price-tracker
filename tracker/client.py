"""HTTP access to Amazon product pages."""
from __future__ import annotations

import logging
from pathlib import Path

from curl_cffi import requests

from .errors import BlockedError, FetchError, ParseError
from .parsing import ProductSnapshot, normalize_product_url, parse_product_page

logger = logging.getLogger(__name__)

# curl_cffi reproduces the TLS/HTTP2 fingerprint of a real browser. Do not set a
# custom User-Agent: a header that disagrees with the fingerprint is easier to spot.
IMPERSONATE = "chrome120"
REQUEST_TIMEOUT_SECONDS = 15
COOKIES = {"i18n-prefs": "EUR", "lc-main": "en_US"}
HEADERS = {"Accept-Language": "en-US,en;q=0.9"}


def fetch_product(url: str, debug_dir: Path | None = None) -> ProductSnapshot:
    """Download a product page and parse it.

    Args:
        url: any amazon.de product link; it is normalized to ``/dp/<ASIN>``.
        debug_dir: if set, the HTML of pages that fail to parse is saved there.

    Raises:
        AmazonError: (or a subclass) for every expected failure.
    """
    canonical_url, asin = normalize_product_url(url)
    try:
        response = requests.get(
            canonical_url,
            headers=HEADERS,
            cookies=COOKIES,
            impersonate=IMPERSONATE,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # curl_cffi raises different exception types across versions
        raise FetchError("Couldn't reach Amazon. Please try again later.") from exc

    if response.status_code in (429, 503):
        raise BlockedError("Amazon is throttling requests right now. Please try again later.")
    if response.status_code != 200:
        raise FetchError(f"Amazon answered with HTTP {response.status_code}.")

    try:
        return parse_product_page(response.text, asin)
    except ParseError:
        logger.warning("Could not parse price for %s", asin)
        if debug_dir is not None:
            _save_debug_html(debug_dir, asin, response.text)
        raise


def _save_debug_html(directory: Path, asin: str, html: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{asin}.html"
    path.write_text(html, encoding="utf-8")
    logger.info("Saved page for inspection: %s", path)

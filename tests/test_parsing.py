import pytest

from tracker.errors import BlockedError, InvalidUrlError, ParseError
from tracker.parsing import normalize_product_url, parse_product_page

ASIN = "B0FN7ZG39D"


def page(body: str) -> str:
    return f'<html><head><title>Amazon.de</title></head><body><span id="productTitle"> Test  Product </span>{body}</body></html>'


def test_standard_layout_ignores_struck_through_list_price():
    html = page(
        '<div id="corePriceDisplay_desktop_feature_div">'
        '<span class="a-price a-text-price" data-a-strike="true"><span class="a-offscreen">€499.00</span></span>'
        '<span class="a-price aok-align-center priceToPay"><span class="a-offscreen">€389.00</span></span>'
        "</div>"
    )
    snapshot = parse_product_page(html, ASIN)
    assert snapshot.price == 389.0
    assert snapshot.title == "Test Product"


def test_apex_layout_even_when_price_carries_text_price_class():
    html = page(
        '<div id="apex_desktop"><span class="a-price a-text-price apexPriceToPay">'
        '<span class="a-offscreen">389,00 €</span></span></div>'
    )
    assert parse_product_page(html, ASIN).price == 389.0


def test_price_in_buybox_column():
    html = page('<div id="desktop_buybox"><span class="a-price priceToPay"><span class="a-offscreen">€12.50</span></span></div>')
    assert parse_product_page(html, ASIN).price == 12.5


def test_generic_price_inside_core_container():
    html = page('<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">€12,50</span></span></div>')
    assert parse_product_page(html, ASIN).price == 12.5


def test_per_unit_price_is_skipped():
    html = page(
        '<div id="corePrice_feature_div">'
        '<span class="pricePerUnit"><span class="a-price"><span class="a-offscreen">€0.39</span></span></span>'
        '<span class="a-price"><span class="a-offscreen">€3.90</span></span></div>'
    )
    assert parse_product_page(html, ASIN).price == 3.9


def test_hidden_field_fallback():
    html = page('<input type="hidden" id="twister-plus-price-data-price" value="389.00">')
    assert parse_product_page(html, ASIN).price == 389.0


def test_unavailable_product_never_uses_prices_from_other_blocks():
    html = page(
        '<div id="outOfStockBuyBox_feature_div"><div id="availability">Currently unavailable.</div></div>'
        '<div id="sims"><span class="a-price"><span class="a-offscreen">€78.99</span></span></div>'
    )
    snapshot = parse_product_page(html, ASIN)
    assert snapshot.price is None


def test_german_unavailable_marker():
    html = page('<div id="availability"><span>Derzeit nicht verfügbar.</span></div>')
    assert parse_product_page(html, ASIN).price is None


def test_missing_price_with_buy_button_is_a_parse_error():
    html = page('<div id="corePrice_feature_div"></div><input id="add-to-cart-button" type="submit">')
    with pytest.raises(ParseError):
        parse_product_page(html, ASIN)


def test_captcha_page():
    html = "<html><body>Sorry! Contact api-services-support@amazon.com</body></html>"
    with pytest.raises(BlockedError):
        parse_product_page(html, ASIN)


def test_large_page_is_never_mistaken_for_captcha():
    body = '<div id="desktop_buybox"><span class="priceToPay"><span class="a-offscreen">€1.00</span></span></div>'
    html = page(body) + "x" * 200_000 + "api-services-support@amazon.com"
    assert parse_product_page(html, ASIN).price == 1.0


def test_normalize_product_url_strips_tracking_and_slug():
    messy = (
        "look: https://www.amazon.de/-/en/Playstation%C2%AE5-Digital-Edition-825-GB/dp/B0FN7ZG39D"
        "?ref_=Oct_d_obs_d_20904927031_3&pd_rd_w=pzfBm&th=1"
    )
    assert normalize_product_url(messy) == (f"https://www.amazon.de/dp/{ASIN}", ASIN)


@pytest.mark.parametrize(
    "text",
    [
        "no link here",
        "https://example.com/dp/B0FN7ZG39D",
        "https://www.amazon.com/dp/B0FN7ZG39D",
        "https://www.amazon.de/s?k=playstation",
    ],
)
def test_normalize_product_url_rejects_unsupported_input(text):
    with pytest.raises(InvalidUrlError):
        normalize_product_url(text)


def test_real_layout_empty_price_to_pay_falls_back_and_ignores_carousel():
    """Layout seen on a real amazon.de page: the main block is empty, the price sits in
    #corePrice_feature_div, and carousels further down contain unrelated (even absurd) prices."""
    html = page(
        '<div id="corePriceDisplay_desktop_feature_div">'
        '<span class="a-price priceToPay"><span class="a-offscreen"></span></span>'
        '<span class="a-price a-text-price" data-a-strike="true"><span class="a-offscreen">\u20ac79.99</span></span>'
        "</div>"
        '<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">\u20ac70.99</span></span></div>'
        '<div id="CardInstanceX"><span class="a-price"><span class="a-offscreen">\u20ac7899</span></span></div>'
        '<input id="add-to-cart-button" type="submit">'
    )
    assert parse_product_page(html, ASIN).price == 70.99


def test_missing_price_error_mentions_delivery_country():
    html = page(
        '<span id="glow-ingress-line2">  Russian Federation </span>'
        '<div id="corePrice_feature_div"></div><input id="add-to-cart-button" type="submit">'
    )
    with pytest.raises(ParseError, match="Russian Federation"):
        parse_product_page(html, ASIN)

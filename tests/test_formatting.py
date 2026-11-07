import pytest

from tracker.formatting import format_price, parse_price, product_link


@pytest.mark.parametrize(
    "text, expected",
    [
        ("€389.00", 389.0),
        ("389,00 €", 389.0),
        ("389,00\u00a0€", 389.0),
        ("1.299,00 €", 1299.0),
        ("€1,299.00", 1299.0),
        ("€ 7,899.00", 7899.0),
        ("1.299", 1299.0),
        ("78,99", 78.99),  # regression: used to become 7899
        ("170,5", 170.5),
        ("199", 199.0),
        ("€389.00 (€389.00 / Stück)", 389.0),
        ("", None),
        (None, None),
        ("free", None),
        ("0", None),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_format_price():
    assert format_price(1299.5) == "€1,299.50"
    assert format_price(None) == "unavailable"


def test_product_link_escapes_html_and_shortens():
    link = product_link("Pad <b>& Co</b> " + "x" * 200, "https://www.amazon.de/dp/B0FN7ZG39D?a=1&b=2")
    assert "<b>" not in link
    assert "&lt;b&gt;" in link
    assert 'href="https://www.amazon.de/dp/B0FN7ZG39D?a=1&amp;b=2"' in link
    assert link.endswith("…</a>")

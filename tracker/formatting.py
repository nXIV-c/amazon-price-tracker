"""Price parsing and Telegram message formatting helpers."""
from __future__ import annotations

import html
import re
import textwrap

_NUMBER_RE = re.compile(r"\d[\d.,\u00a0\u202f]*")
_NBSP_RE = re.compile(r"[\u00a0\u202f]")
_SEPARATORS_RE = re.compile(r"[.,]")


def parse_price(text: str | None) -> float | None:
    """Return the first positive number found in ``text``.

    Understands German ("1.299,00 €") and English ("€1,299.00") notation. The last
    separator is the decimal mark only when it is followed by one or two digits;
    otherwise every separator is a thousands separator ("1.299" -> 1299).
    """
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if match is None:
        return None

    raw = _NBSP_RE.sub("", match.group()).rstrip(".,")
    last_separator = max(raw.rfind("."), raw.rfind(","))
    if last_separator == -1:
        normalized = raw
    else:
        integer_part = _SEPARATORS_RE.sub("", raw[:last_separator])
        decimals = raw[last_separator + 1:]
        normalized = f"{integer_part}.{decimals}" if len(decimals) <= 2 else f"{integer_part}{decimals}"

    try:
        value = float(normalized)
    except ValueError:
        return None
    return value if value > 0 else None


def format_price(value: float | None) -> str:
    """Format a price for display; ``None`` means the product is unavailable."""
    return "unavailable" if value is None else f"€{value:,.2f}"


def product_link(title: str, url: str, max_length: int = 80) -> str:
    """Return an HTML link with a shortened, escaped title (Telegram HTML mode)."""
    short_title = textwrap.shorten(title, width=max_length, placeholder="…")
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(short_title)}</a>'

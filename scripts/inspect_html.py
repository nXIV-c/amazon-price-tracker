"""Developer tool: show how the parser sees a saved Amazon page.

Set DEBUG_HTML_DIR=debug in .env, let the bot hit a page it cannot parse, then run:

    python -m scripts.inspect_html debug/B0FN7ZG39D.html
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from bs4 import BeautifulSoup

from tracker.errors import AmazonError
from tracker.parsing import parse_product_page

_BLOCKS = ("#availability", "#outOfStock", "#outOfStockBuyBox_feature_div", "#buybox")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("html_file", type=Path)
    path = parser.parse_args().html_file
    if not path.is_file():
        raise SystemExit(f"File not found: {path}. Save the product page there first (see the README).")

    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    print(f"File: {path} ({len(html):,} characters)")
    print(f"<title>: {soup.title.get_text(strip=True) if soup.title else '-'}")

    print("\n.a-price elements (price, classes, nearest ancestor with an id):")
    for element in soup.select(".a-price")[:25]:
        offscreen = element.select_one(".a-offscreen")
        anchor = element.find_parent(id=True)
        print(
            f"  {offscreen.get_text(strip=True) if offscreen else '?':>12} | "
            f"strike={element.get('data-a-strike', '-'):<5} | "
            f"{' '.join(element.get('class', []))} | in #{anchor.get('id') if anchor else '-'}"
        )

    print("\nBuy button present:", bool(soup.select_one("#add-to-cart-button, input[name='submit.add-to-cart']")))
    for selector in _BLOCKS:
        block = soup.select_one(selector)
        if block is not None:
            text = textwrap.shorten(block.get_text(" ", strip=True), 160, placeholder="…")
            print(f"{selector}: {text!r}")

    print("\nParser verdict:")
    try:
        snapshot = parse_product_page(html, asin=path.stem)
        print(f"  OK: title={snapshot.title[:60]!r} price={snapshot.price}")
    except AmazonError as exc:
        print(f"  {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()

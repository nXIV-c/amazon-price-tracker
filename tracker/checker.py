"""Background job that re-checks every tracked product and sends alerts."""
from __future__ import annotations

import logging
import random
import threading
from collections import defaultdict
from typing import TYPE_CHECKING

from .alerts import decide_alert
from .client import fetch_product
from .config import Settings
from .database import Database, TrackedProduct
from .errors import AmazonError
from .formatting import format_price, product_link
from .parsing import ProductSnapshot

if TYPE_CHECKING:
    from telebot import TeleBot

logger = logging.getLogger(__name__)


class PriceChecker:
    def __init__(self, database: Database, bot: TeleBot, settings: Settings, stop_event: threading.Event) -> None:
        self._db = database
        self._bot = bot
        self._settings = settings
        self._stop = stop_event

    def run_forever(self) -> None:
        """Check immediately, then once per interval, until ``stop_event`` is set."""
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:  # keep the thread alive no matter what
                logger.exception("Price check cycle crashed")
            self._stop.wait(self._settings.check_interval_seconds)

    def check_once(self) -> None:
        # Users tracking the same product share a single request.
        by_url: dict[str, list[TrackedProduct]] = defaultdict(list)
        for product in self._db.all_products():
            by_url[product.url].append(product)
        logger.info("Checking %d page(s)", len(by_url))

        for url, watchers in by_url.items():
            if self._stop.is_set():
                return
            try:
                snapshot = fetch_product(url, debug_dir=self._settings.debug_html_dir)
            except AmazonError as exc:
                logger.warning("Skipping %s: %s", url, exc)
            else:
                for product in watchers:
                    self._process(product, snapshot)
            # Pause after every request, successful or not, with jitter.
            self._stop.wait(self._settings.request_delay_seconds * random.uniform(0.8, 1.5))

    def _process(self, product: TrackedProduct, snapshot: ProductSnapshot) -> None:
        send, alerted = decide_alert(product.target_price, snapshot.price, product.alert_sent)
        if send:
            try:
                self._send_alert(product, snapshot)
            except Exception:  # e.g. the user blocked the bot; one bad chat must not stop the rest
                logger.exception("Could not alert chat %s about %s", product.telegram_id, product.asin)
                alerted = False  # retry on the next cycle
        self._db.update_price(product.id, snapshot.price, alerted)

    def _send_alert(self, product: TrackedProduct, snapshot: ProductSnapshot) -> None:
        text = (
            "🚨 <b>Price drop alert!</b>\n\n"
            f"📌 {product_link(product.title, product.url)}\n"
            f"📉 <b>Now:</b> {format_price(snapshot.price)}\n"
            f"🎯 <b>Your target:</b> {format_price(product.target_price)}"
        )
        self._bot.send_message(product.telegram_id, text)

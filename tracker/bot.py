"""Telegram bot: commands, the guided /add flow and the tracked-products list."""
from __future__ import annotations

import logging

import telebot
from telebot import apihelper, types

from .client import fetch_product
from .config import Settings
from .database import Database
from .errors import AmazonError, InvalidUrlError
from .formatting import format_price, parse_price, product_link
from .limits import RateLimiter
from .parsing import URL_RE, ProductSnapshot, normalize_product_url

logger = logging.getLogger(__name__)

# Minimum seconds between two uses of the same action by the same user.
COOLDOWNS = {"add": 3, "list": 2, "delete": 1}
DELETE_PREFIX = "del_"

HELP_TEXT = (
    "👋 <b>Amazon Price Tracker</b>\n\n"
    "I watch amazon.de prices and message you when one drops to your target.\n\n"
    "<b>Commands</b>\n"
    "/add — guided: I ask for the link, then for the target price\n"
    "<code>/add &lt;link&gt; &lt;target price&gt;</code> — one-line version\n"
    "/list — show and manage tracked products\n\n"
    "<b>Example</b>\n"
    "<code>/add https://www.amazon.de/dp/B0FN7ZG39D 350</code>"
)


class PriceTrackerBot:
    """Connects Telegram handlers to the database and the Amazon client."""

    def __init__(self, settings: Settings, database: Database) -> None:
        if settings.telegram_api_url:
            apihelper.API_URL = settings.telegram_api_url
        self._settings = settings
        self._db = database
        self._limiters = {action: RateLimiter(seconds) for action, seconds in COOLDOWNS.items()}
        # HTML is the default parse mode: user-controlled text goes through html.escape,
        # whereas Markdown breaks on "_", "*" or "[" inside product titles.
        self.bot = telebot.TeleBot(settings.bot_token, parse_mode="HTML")
        self._register_handlers()

    # ------------------------------------------------------------------ setup

    def _register_handlers(self) -> None:
        bot = self.bot
        # Registered first: the first matching handler wins.
        bot.register_message_handler(self._deny, func=self._is_denied)
        bot.register_message_handler(self._on_start, commands=["start", "help"])
        bot.register_message_handler(self._on_add, commands=["add"])
        bot.register_message_handler(self._on_list, commands=["list"])
        bot.register_callback_query_handler(
            self._on_delete, func=lambda call: (call.data or "").startswith(DELETE_PREFIX)
        )
        try:
            bot.set_my_commands(
                [
                    types.BotCommand("start", "👋 Start & help"),
                    types.BotCommand("add", "➕ Track an Amazon product"),
                    types.BotCommand("list", "📋 Show tracked products"),
                ]
            )
        except Exception:
            logger.warning("Could not set the command menu", exc_info=True)

    # ----------------------------------------------------------------- guards

    def _is_allowed(self, user_id: int) -> bool:
        return self._settings.is_user_allowed(user_id)

    def _is_denied(self, message: types.Message) -> bool:
        return message.from_user is None or not self._is_allowed(message.from_user.id)

    def _is_rate_limited(self, user_id: int, action: str) -> bool:
        return self._limiters[action].is_limited(user_id)

    @staticmethod
    def _slow_down_text(action: str) -> str:
        return f"⚠️ Slow down: please wait {COOLDOWNS[action]} seconds between requests."

    def _limit_reached(self, chat_id: int, asin: str) -> bool:
        """True if the user is at their product limit and ``asin`` would be a new product."""
        return self._db.is_product_limit_reached(chat_id, asin, self._settings.max_products_per_user)

    def _limit_text(self) -> str:
        return (
            f"⚠️ Limit reached: you can track up to {self._settings.max_products_per_user} products. "
            "Remove one with /list first."
        )

    @staticmethod
    def _is_command(message: types.Message) -> bool:
        return (message.text or "").startswith("/")

    def _cancel(self, message: types.Message) -> None:
        self.bot.reply_to(message, "Cancelled. Send your command again.")

    # --------------------------------------------------------------- commands

    def _deny(self, message: types.Message) -> None:
        self.bot.reply_to(message, "⛔ Access denied. You are not authorized to use this bot.")

    def _on_start(self, message: types.Message) -> None:
        self.bot.reply_to(message, HELP_TEXT)

    def _on_add(self, message: types.Message) -> None:
        if self._is_rate_limited(message.from_user.id, "add"):
            self.bot.reply_to(message, self._slow_down_text("add"))
            return

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:  # guided mode
            prompt = self.bot.reply_to(message, "📥 <b>Send me the amazon.de product link:</b>")
            self.bot.register_next_step_handler(prompt, self._on_link)
            return
        self._add_in_one_line(message, parts[1])

    def _add_in_one_line(self, message: types.Message, arguments: str) -> None:
        usage = "⚠️ Use <code>/add &lt;link&gt; &lt;target price&gt;</code> or just /add for the guided mode."
        try:
            url, asin = normalize_product_url(arguments)
        except InvalidUrlError as exc:
            self.bot.reply_to(message, f"❌ {exc}\n\n{usage}")
            return
        target_price = parse_price(URL_RE.sub("", arguments))
        if target_price is None:
            self.bot.reply_to(message, usage)
            return
        if self._limit_reached(message.chat.id, asin):  # refuse before spending an Amazon request
            self.bot.reply_to(message, self._limit_text())
            return

        status = self.bot.reply_to(message, "⏳ Fetching product details from Amazon…")
        snapshot = self._fetch(url, status)
        if snapshot is not None:
            text = self._start_tracking(message.chat.id, url, snapshot, target_price)
            self.bot.edit_message_text(text, status.chat.id, status.message_id)

    # ------------------------------------------------------- guided add steps

    def _on_link(self, message: types.Message) -> None:
        if self._is_command(message):
            self._cancel(message)
            return
        try:
            url, asin = normalize_product_url(message.text or "")
        except InvalidUrlError as exc:
            self.bot.reply_to(message, f"❌ {exc}\nSend /add to try again.")
            return
        if self._limit_reached(message.chat.id, asin):  # refuse before spending an Amazon request
            self.bot.reply_to(message, self._limit_text())
            return

        status = self.bot.reply_to(message, "⏳ Fetching product details from Amazon…")
        snapshot = self._fetch(url, status)
        if snapshot is None:
            return

        prompt = self.bot.edit_message_text(
            f"📦 {product_link(snapshot.title, url, 75)}\n"
            f"💵 <b>Current price:</b> {format_price(snapshot.price)}\n\n"
            "🎯 <b>Enter your target price in € (e.g. 200 or 199.99):</b>",
            status.chat.id,
            status.message_id,
            disable_web_page_preview=True,
        )
        self.bot.register_next_step_handler(prompt, self._on_target_price, url, snapshot)

    def _on_target_price(self, message: types.Message, url: str, snapshot: ProductSnapshot) -> None:
        if self._is_command(message):
            self._cancel(message)
            return
        target_price = parse_price(message.text)
        if target_price is None:
            self.bot.reply_to(message, "❌ That's not a valid price. Send /add to start again.")
            return
        self.bot.reply_to(message, self._start_tracking(message.chat.id, url, snapshot, target_price))

    # ---------------------------------------------------------------- helpers

    def _fetch(self, url: str, status: types.Message) -> ProductSnapshot | None:
        """Fetch a product; on failure, turn the status message into an error and return None."""
        try:
            return fetch_product(url, debug_dir=self._settings.debug_html_dir)
        except AmazonError as exc:
            logger.warning("Fetch failed for %s: %s", url, exc)
            self.bot.edit_message_text(f"❌ {exc}", status.chat.id, status.message_id)
            return None

    def _start_tracking(self, chat_id: int, url: str, snapshot: ProductSnapshot, target_price: float) -> str:
        """Persist the product and return the confirmation text."""
        self._db.upsert_product(chat_id, snapshot.asin, url, snapshot.title, target_price, snapshot.price)

        if snapshot.price is None:
            note = "ℹ️ It's unavailable right now. I'll alert you once it's back at or below your target."
        elif target_price >= snapshot.price:
            note = "ℹ️ Your target isn't below the current price, so you'll be alerted on the next check."
        else:
            note = "I'll message you as soon as the price drops to your target."
        return (
            "✅ <b>Now tracking</b>\n\n"
            f"📌 {product_link(snapshot.title, url)}\n"
            f"💵 <b>Current price:</b> {format_price(snapshot.price)}\n"
            f"🎯 <b>Target price:</b> {format_price(target_price)}\n\n"
            f"{note}"
        )

    # ------------------------------------------------------------ list/delete

    def _on_list(self, message: types.Message) -> None:
        if self._is_rate_limited(message.from_user.id, "list"):
            self.bot.reply_to(message, self._slow_down_text("list"))
            return
        products = self._db.user_products(message.chat.id)
        if not products:
            self.bot.reply_to(message, "📋 Your list is empty. Use /add to track a product.")
            return

        self.bot.send_message(message.chat.id, f"📋 <b>Tracked products ({len(products)}):</b>")
        for product in products:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🗑 Delete", callback_data=f"{DELETE_PREFIX}{product.id}"))
            self.bot.send_message(
                message.chat.id,
                f"📌 {product_link(product.title, product.url, 75)}\n"
                f"💵 <b>Now:</b> {format_price(product.last_price)} · "
                f"🎯 <b>Target:</b> {format_price(product.target_price)}",
                reply_markup=markup,
                disable_web_page_preview=True,
            )

    def _on_delete(self, call: types.CallbackQuery) -> None:
        if not self._is_allowed(call.from_user.id):
            self.bot.answer_callback_query(call.id, "Access denied.")
            return
        if self._is_rate_limited(call.from_user.id, "delete"):
            self.bot.answer_callback_query(call.id, "Slow down.")
            return
        try:
            product_id = int(call.data.removeprefix(DELETE_PREFIX))
        except ValueError:
            self.bot.answer_callback_query(call.id, "Invalid request.")
            return

        deleted = self._db.delete_product(product_id, call.message.chat.id)
        self.bot.answer_callback_query(call.id, "Removed." if deleted else "Already removed.")
        self.bot.edit_message_text("🗑 Removed from your list.", call.message.chat.id, call.message.message_id)

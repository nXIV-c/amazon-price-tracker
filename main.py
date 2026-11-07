"""Entry point: set up storage, start the background checker, run the bot."""
from __future__ import annotations

import logging
import threading

from tracker.bot import PriceTrackerBot
from tracker.checker import PriceChecker
from tracker.config import load_settings
from tracker.database import Database

logger = logging.getLogger("tracker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except RuntimeError as exc:  # a readable message instead of a traceback
        raise SystemExit(f"Configuration error: {exc}") from exc
    if settings.allow_everyone:
        logger.warning("ALLOW_EVERYONE is on: the bot accepts requests from everyone.")

    database = Database(settings.database_path)
    database.init()

    app = PriceTrackerBot(settings, database)
    stop_event = threading.Event()
    checker = PriceChecker(database, app.bot, settings, stop_event)
    threading.Thread(target=checker.run_forever, name="price-checker", daemon=True).start()

    logger.info("Bot is running.")
    try:
        app.bot.infinity_polling(skip_pending=True)
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()

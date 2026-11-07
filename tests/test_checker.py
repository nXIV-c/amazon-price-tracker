import threading
from pathlib import Path

from tracker import checker as checker_module
from tracker.checker import PriceChecker
from tracker.config import Settings
from tracker.database import Database
from tracker.parsing import ProductSnapshot

URL = "https://www.amazon.de/dp/B0FN7ZG39D"


class FakeBot:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def build(tmp_path, monkeypatch, prices):
    """`prices` is a list consumed one fetch at a time."""
    settings = Settings(
        bot_token="x",
        allowed_user_ids=frozenset(),
        telegram_api_url=None,
        database_path=Path(tmp_path) / "t.db",
        check_interval_seconds=1,
        request_delay_seconds=0,
        debug_html_dir=None,
    )
    db = Database(settings.database_path)
    db.init()
    fetches = []

    def fake_fetch(url, debug_dir=None):
        fetches.append(url)
        return ProductSnapshot("B0FN7ZG39D", "PS5 <Slim>", prices.pop(0))

    monkeypatch.setattr(checker_module, "fetch_product", fake_fetch)
    bot = FakeBot()
    return db, bot, fetches, PriceChecker(db, bot, settings, threading.Event())


def test_alerts_once_per_drop_and_shares_requests(tmp_path, monkeypatch):
    db, bot, fetches, checker = build(tmp_path, monkeypatch, [90.0, 90.0, 120.0, 80.0])
    db.upsert_product(1, "B0FN7ZG39D", URL, "PS5 <Slim>", 100.0, 150.0)
    db.upsert_product(2, "B0FN7ZG39D", URL, "PS5 <Slim>", 95.0, 150.0)

    checker.check_once()
    assert fetches == [URL]  # two watchers, one request
    assert sorted(chat for chat, _ in bot.sent) == [1, 2]
    assert "&lt;Slim&gt;" in bot.sent[0][1]  # titles are escaped

    checker.check_once()  # still below the target: no repeat
    assert len(bot.sent) == 2

    checker.check_once()  # back above: re-armed, no alert
    assert len(bot.sent) == 2

    checker.check_once()  # drops again: alert again
    assert len(bot.sent) == 4

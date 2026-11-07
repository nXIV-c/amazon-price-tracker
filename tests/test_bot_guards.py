"""Access control and limits of the Telegram handlers, with Telegram replaced by a recording fake."""
from types import SimpleNamespace

import pytest

from tracker import bot as bot_module
from tracker.config import Settings
from tracker.database import Database
from tracker.parsing import ProductSnapshot

LINK = "https://www.amazon.de/dp/B0FN7ZG39D"


class FakeTeleBot:
    """Records what the bot would send. Setup calls (register_*, set_my_commands...) do nothing."""

    def __init__(self, *args, **kwargs):
        self.sent = []

    def __getattr__(self, name):
        def do_nothing(*args, **kwargs):
            return None

        return do_nothing

    def reply_to(self, message, text, **kwargs):
        self.sent.append(text)
        return SimpleNamespace(chat=message.chat, message_id=1)

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        self.sent.append(text)
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=message_id)

    def answer_callback_query(self, call_id, text=None, **kwargs):
        self.sent.append(text)


@pytest.fixture
def make_bot(tmp_path, monkeypatch):
    monkeypatch.setattr(bot_module.telebot, "TeleBot", FakeTeleBot)

    def build(allowed_user_ids=frozenset({1}), **overrides):
        settings = Settings(
            bot_token="1:test",
            allowed_user_ids=allowed_user_ids,
            telegram_api_url=None,
            database_path=tmp_path / "test.db",
            check_interval_seconds=60,
            request_delay_seconds=0,
            debug_html_dir=None,
            **overrides,
        )
        database = Database(settings.database_path)
        database.init()
        return bot_module.PriceTrackerBot(settings, database), database

    return build


def message(user_id, text):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id), chat=SimpleNamespace(id=user_id), text=text, message_id=1
    )


def test_strangers_are_denied(make_bot):
    app, _ = make_bot()
    assert app._is_denied(message(2, "/list")) is True
    assert app._is_denied(message(1, "/list")) is False
    assert app._is_denied(SimpleNamespace(from_user=None)) is True


def test_everyone_is_admitted_only_when_switched_on(make_bot):
    app, _ = make_bot(allowed_user_ids=frozenset(), allow_everyone=True)
    assert app._is_denied(message(12345, "/list")) is False


def test_an_empty_allow_list_admits_nobody(make_bot):
    app, _ = make_bot(allowed_user_ids=frozenset())
    assert app._is_denied(message(1, "/list")) is True


def test_list_is_rate_limited(make_bot):
    app, _ = make_bot()
    app._on_list(message(1, "/list"))
    app._on_list(message(1, "/list"))
    assert "empty" in app.bot.sent[0]
    assert "Slow down" in app.bot.sent[1]


def test_delete_buttons_are_rate_limited(make_bot):
    app, _ = make_bot()
    call = SimpleNamespace(
        id="call-1",
        data=f"{bot_module.DELETE_PREFIX}1",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=5),
    )
    app._on_delete(call)
    app._on_delete(call)
    assert "Slow down." in app.bot.sent


def test_the_product_limit_refuses_before_any_amazon_request(make_bot, monkeypatch):
    app, database = make_bot(max_products_per_user=1)
    database.upsert_product(1, "B000000001", "u", "Old", 10.0, 20.0)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("Amazon must not be contacted when the limit is reached")

    monkeypatch.setattr(bot_module, "fetch_product", must_not_be_called)

    app._add_in_one_line(message(1, f"/add {LINK} 100"), f"{LINK} 100")
    app._on_link(message(1, LINK))
    assert all("Limit reached" in text for text in app.bot.sent)
    assert len(app.bot.sent) == 2
    assert len(database.user_products(1)) == 1


def test_re_adding_a_tracked_product_still_works_at_the_limit(make_bot, monkeypatch):
    app, database = make_bot(max_products_per_user=1)
    database.upsert_product(1, "B0FN7ZG39D", LINK, "PS5", 300.0, 399.0)
    monkeypatch.setattr(
        bot_module, "fetch_product", lambda url, debug_dir=None: ProductSnapshot("B0FN7ZG39D", "PS5", 399.0)
    )

    app._add_in_one_line(message(1, f"/add {LINK} 250"), f"{LINK} 250")
    assert any("Now tracking" in text for text in app.bot.sent)
    assert database.user_products(1)[0].target_price == 250.0

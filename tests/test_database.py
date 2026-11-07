import pytest

from tracker.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "nested" / "test.db")
    database.init()
    return database


def test_adding_the_same_product_twice_updates_the_target(db):
    db.upsert_product(1, "B0FN7ZG39D", "https://www.amazon.de/dp/B0FN7ZG39D", "PS5", 300.0, 399.0)
    db.upsert_product(1, "B0FN7ZG39D", "https://www.amazon.de/dp/B0FN7ZG39D", "PS5", 350.0, 399.0)
    products = db.user_products(1)
    assert len(products) == 1
    assert products[0].target_price == 350.0


def test_update_price_and_alert_flag(db):
    db.upsert_product(1, "B0FN7ZG39D", "u", "PS5", 300.0, 399.0)
    product = db.all_products()[0]
    db.update_price(product.id, None, True)
    updated = db.all_products()[0]
    assert updated.last_price is None
    assert updated.alert_sent is True


def test_users_can_only_delete_their_own_products(db):
    db.upsert_product(1, "B0FN7ZG39D", "u", "PS5", 300.0, 399.0)
    product_id = db.all_products()[0].id
    assert db.delete_product(product_id, telegram_id=2) is False
    assert db.delete_product(product_id, telegram_id=1) is True
    assert db.all_products() == []


def _track(db, user_id, asin):
    db.upsert_product(user_id, asin, f"https://www.amazon.de/dp/{asin}", asin, 10.0, 20.0)


def test_a_new_product_is_refused_once_the_limit_is_reached(db):
    _track(db, 1, "AAAAAAAAAA")
    _track(db, 1, "BBBBBBBBBB")
    assert db.is_product_limit_reached(1, "CCCCCCCCCC", limit=2) is True
    assert db.is_product_limit_reached(1, "CCCCCCCCCC", limit=3) is False


def test_re_adding_a_tracked_product_is_allowed_at_the_limit(db):
    _track(db, 1, "AAAAAAAAAA")
    _track(db, 1, "BBBBBBBBBB")
    assert db.is_product_limit_reached(1, "AAAAAAAAAA", limit=2) is False


def test_the_limit_is_counted_per_user(db):
    _track(db, 1, "AAAAAAAAAA")
    _track(db, 1, "BBBBBBBBBB")
    assert db.is_product_limit_reached(2, "AAAAAAAAAA", limit=2) is False

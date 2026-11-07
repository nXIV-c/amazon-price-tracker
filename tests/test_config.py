import pytest

from tracker import config


@pytest.fixture
def env(monkeypatch):
    """A clean environment: a real .env file in the working directory must not leak into the tests."""
    for name in ("ALLOWED_USER_IDS", "ALLOW_EVERYONE", "MAX_PRODUCTS_PER_USER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    return monkeypatch


def test_missing_token_is_reported(env):
    env.delenv("BOT_TOKEN")
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        config.load_settings()


def test_an_empty_allow_list_is_refused_by_default(env):
    with pytest.raises(RuntimeError, match="ALLOWED_USER_IDS"):
        config.load_settings()


def test_the_allow_list_admits_only_listed_users(env):
    env.setenv("ALLOWED_USER_IDS", "1, 2")
    settings = config.load_settings()
    assert settings.is_user_allowed(1)
    assert settings.is_user_allowed(2)
    assert not settings.is_user_allowed(3)


def test_a_malformed_allow_list_is_rejected(env):
    env.setenv("ALLOWED_USER_IDS", "12,abc")
    with pytest.raises(RuntimeError, match="comma-separated"):
        config.load_settings()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_allow_everyone_must_be_switched_on_explicitly(env, value):
    env.setenv("ALLOW_EVERYONE", value)
    settings = config.load_settings()
    assert settings.allow_everyone
    assert settings.is_user_allowed(999)


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "nope"])
def test_other_values_do_not_open_the_bot(env, value):
    env.setenv("ALLOWED_USER_IDS", "1")
    env.setenv("ALLOW_EVERYONE", value)
    settings = config.load_settings()
    assert not settings.allow_everyone
    assert not settings.is_user_allowed(999)


def test_product_limit_has_a_default_and_can_be_changed(env):
    env.setenv("ALLOWED_USER_IDS", "1")
    assert config.load_settings().max_products_per_user == config.DEFAULT_MAX_PRODUCTS_PER_USER
    env.setenv("MAX_PRODUCTS_PER_USER", "5")
    assert config.load_settings().max_products_per_user == 5


@pytest.mark.parametrize("value", ["0", "-3", "many"])
def test_invalid_product_limits_are_rejected(env, value):
    env.setenv("ALLOWED_USER_IDS", "1")
    env.setenv("MAX_PRODUCTS_PER_USER", value)
    with pytest.raises(RuntimeError, match="MAX_PRODUCTS_PER_USER"):
        config.load_settings()

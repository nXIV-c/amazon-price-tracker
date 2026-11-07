"""Application settings, loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MAX_PRODUCTS_PER_USER = 20
_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_ids: frozenset[int]  # the allow-list: only these Telegram users may use the bot
    telegram_api_url: str | None  # optional proxy, e.g. "https://host/bot{0}/{1}"
    database_path: Path
    check_interval_seconds: int
    request_delay_seconds: float
    debug_html_dir: Path | None  # where to save pages that failed to parse
    allow_everyone: bool = False  # explicit opt-in: ignore the allow-list and accept anyone
    max_products_per_user: int = DEFAULT_MAX_PRODUCTS_PER_USER

    def is_user_allowed(self, user_id: int) -> bool:
        """Deny by default: access needs an allow-list entry or the explicit ``allow_everyone`` switch."""
        return self.allow_everyone or user_id in self.allowed_user_ids


def _parse_user_ids(raw: str) -> frozenset[int]:
    try:
        return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)
    except ValueError as exc:
        raise RuntimeError("ALLOWED_USER_IDS must be a comma-separated list of integers.") from exc


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in _TRUE_VALUES


def _parse_max_products(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("MAX_PRODUCTS_PER_USER must be a whole number.") from exc
    if value < 1:
        raise RuntimeError("MAX_PRODUCTS_PER_USER must be at least 1.")
    return value


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    allowed_user_ids = _parse_user_ids(os.getenv("ALLOWED_USER_IDS", ""))
    allow_everyone = _parse_bool(os.getenv("ALLOW_EVERYONE", ""))
    if not allowed_user_ids and not allow_everyone:
        raise RuntimeError(
            "ALLOWED_USER_IDS is empty, so nobody could use the bot. Put your Telegram user ID there "
            "(you can get it from @userinfobot), or set ALLOW_EVERYONE=true to run an open bot on purpose."
        )

    debug_dir = os.getenv("DEBUG_HTML_DIR")
    return Settings(
        bot_token=token,
        allowed_user_ids=allowed_user_ids,
        telegram_api_url=os.getenv("TELEGRAM_API_URL") or None,
        database_path=Path(os.getenv("DATABASE_PATH", "data/tracker.db")),
        check_interval_seconds=int(os.getenv("CHECK_INTERVAL_SECONDS", "14400")),
        request_delay_seconds=float(os.getenv("REQUEST_DELAY_SECONDS", "5")),
        debug_html_dir=Path(debug_dir) if debug_dir else None,
        allow_everyone=allow_everyone,
        max_products_per_user=_parse_max_products(
            os.getenv("MAX_PRODUCTS_PER_USER", str(DEFAULT_MAX_PRODUCTS_PER_USER))
        ),
    )

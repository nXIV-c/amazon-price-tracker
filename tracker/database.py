"""SQLite persistence layer."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER NOT NULL,
    asin          TEXT    NOT NULL,
    product_url   TEXT    NOT NULL,
    product_title TEXT    NOT NULL,
    target_price  REAL    NOT NULL,
    last_price    REAL,
    alert_sent    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (telegram_id, asin)
)
"""
_COLUMNS = "id, telegram_id, asin, product_url, product_title, target_price, last_price, alert_sent"


@dataclass(frozen=True)
class TrackedProduct:
    id: int
    telegram_id: int
    asin: str
    url: str
    title: str
    target_price: float
    last_price: float | None
    alert_sent: bool


def _to_product(row: sqlite3.Row) -> TrackedProduct:
    return TrackedProduct(
        id=row["id"],
        telegram_id=row["telegram_id"],
        asin=row["asin"],
        url=row["product_url"],
        title=row["product_title"],
        target_price=row["target_price"],
        last_price=row["last_price"],
        alert_sent=bool(row["alert_sent"]),
    )


class Database:
    """Thin wrapper that opens a short-lived connection per operation.

    SQLite connections must not be shared between threads, and the bot and the
    price checker run in different threads, so nothing is cached here.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:  # commits on success, rolls back on error
                yield connection
        finally:
            connection.close()  # `with connection` alone does not close it

    def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_SCHEMA)

    def upsert_product(
        self,
        telegram_id: int,
        asin: str,
        url: str,
        title: str,
        target_price: float,
        current_price: float | None,
    ) -> None:
        """Start tracking a product; re-adding it just updates the target price."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tracked_products
                    (telegram_id, asin, product_url, product_title, target_price, last_price)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (telegram_id, asin) DO UPDATE SET
                    product_title = excluded.product_title,
                    target_price  = excluded.target_price,
                    last_price    = excluded.last_price,
                    alert_sent    = 0
                """,
                (telegram_id, asin, url, title, target_price, current_price),
            )

    def is_product_limit_reached(self, telegram_id: int, asin: str, limit: int) -> bool:
        """True if the user already tracks ``limit`` products and ``asin`` is not one of them.

        Re-adding a product that is already tracked only changes its target, so it is never refused.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(asin = ?), 0) AS has_it "
                "FROM tracked_products WHERE telegram_id = ?",
                (asin, telegram_id),
            ).fetchone()
        return row["has_it"] == 0 and row["total"] >= limit

    def all_products(self) -> list[TrackedProduct]:
        with self._connect() as connection:
            rows = connection.execute(f"SELECT {_COLUMNS} FROM tracked_products ORDER BY id").fetchall()
        return [_to_product(row) for row in rows]

    def user_products(self, telegram_id: int) -> list[TrackedProduct]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM tracked_products WHERE telegram_id = ? ORDER BY id",
                (telegram_id,),
            ).fetchall()
        return [_to_product(row) for row in rows]

    def update_price(self, product_id: int, price: float | None, alert_sent: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tracked_products SET last_price = ?, alert_sent = ? WHERE id = ?",
                (price, int(alert_sent), product_id),
            )

    def delete_product(self, product_id: int, telegram_id: int) -> bool:
        """Delete a product owned by ``telegram_id``. Returns False if nothing matched."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM tracked_products WHERE id = ? AND telegram_id = ?",
                (product_id, telegram_id),
            )
        return cursor.rowcount > 0

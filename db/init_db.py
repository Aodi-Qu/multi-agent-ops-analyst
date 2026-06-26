"""SQLite database initialization with operation_metrics table and seed data."""

import sqlite3
import random
import json
from datetime import datetime, timedelta
from typing import Any
from config import settings


# ── SQLite ──────────────────────────────────────────────────────────────

DB_PATH: str = settings.DATABASE_URL.replace("sqlite:///", "")

RNG = random.Random(42)


def get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_sqlite() -> None:
    """Create the operation_metrics table if it does not exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operation_metrics (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT    NOT NULL,
            product_line TEXT    NOT NULL,
            revenue      REAL    NOT NULL,
            cost         REAL    NOT NULL,
            active_users INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    print("[SQLite] Table 'operation_metrics' is ready.")


def seed_data() -> None:
    """
    Insert 60 rows of simulated operation metrics spanning the last 3 months.
    Product lines: smartphone, laptop, tablet, wearable, smart_home
    Date range: roughly 2026-04-01 ~ 2026-06-25 (86 days).
    """
    product_lines: list[str] = [
        "smartphone", "laptop", "tablet", "wearable", "smart_home"
    ]
    start_date: datetime = datetime(2026, 4, 1)
    end_date: datetime = datetime(2026, 6, 25)
    total_days: int = (end_date - start_date).days

    day_indices: list[int] = sorted(
        RNG.sample(range(total_days), min(60, total_days))
    )
    dates: list[str] = [
        (start_date + timedelta(days=d)).strftime("%Y-%m-%d")
        for d in day_indices
    ]

    rows: list[tuple[str, str, float, float, int]] = []
    for dt in dates:
        pl: str = RNG.choice(product_lines)
        base_revenue: float = {
            "smartphone": 5_000_000,
            "laptop": 3_500_000,
            "tablet": 2_000_000,
            "wearable": 800_000,
            "smart_home": 1_200_000,
        }[pl]
        noise: float = RNG.uniform(0.7, 1.3)
        revenue: float = round(base_revenue * noise, 2)
        cost_rate: float = RNG.uniform(0.45, 0.85)
        cost: float = round(revenue * cost_rate, 2)
        active_users: int = {
            "smartphone": RNG.randint(50_000, 500_000),
            "laptop": RNG.randint(30_000, 300_000),
            "tablet": RNG.randint(20_000, 200_000),
            "wearable": RNG.randint(10_000, 100_000),
            "smart_home": RNG.randint(5_000, 80_000),
        }[pl]
        rows.append((dt, pl, revenue, cost, active_users))

    conn = get_connection()
    cur = conn.cursor()
    cur.executemany(
        "INSERT INTO operation_metrics (date, product_line, revenue, cost, active_users) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[Seed] Inserted {len(rows)} rows into operation_metrics.")


# init_chroma moved to main.py
    """Initialize Chroma vector store (lazy init, called on startup)."""
#
#
#


if __name__ == "__main__":
    init_sqlite()
    seed_data()


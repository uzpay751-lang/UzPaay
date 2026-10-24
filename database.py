"""
UzPay PostgreSQL helper for a Python backend/bot.

Install:
    pip install "psycopg[binary,pool]"

Set these environment variables in your HOSTING PROVIDER (not in GitHub code):
    DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE

Then use:
    from database import init_db, get_connection

    await init_db()
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (123456789,),
        )

IMPORTANT:
- Do not put your real password in this file or commit it to GitHub.
- Run this only in a Python server/bot environment, not directly in index.html.
- GitHub Pages only serves static files; it cannot run this Python code. Your backend
  must be deployed to a Python-capable host.
"""

import os
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your backend host's environment variables."
        )
    return url


_pool: AsyncConnectionPool | None = None


async def init_db() -> None:
    """Create the connection pool and the basic users table."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=_database_url(),
            min_size=1,
            max_size=5,
            open=False,
        )
        await _pool.open()

    async with _pool.connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


@asynccontextmanager
async def get_connection():
    """Yield a pooled async PostgreSQL connection."""
    if _pool is None:
        await init_db()
    assert _pool is not None
    async with _pool.connection() as conn:
        yield conn


async def close_db() -> None:
    """Close the connection pool during application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

"""Tests for schema migrations against old and current databases."""
import pytest
from sqlalchemy import text
from sqlmodel import SQLModel, create_engine

from xscimon.database import _apply_migrations


def _column_names(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}


def test_migrations_add_missing_columns_to_old_schema():
    engine = create_engine("sqlite://")
    # Simulate a pre-migration database: account table without the newer columns.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE account (id INTEGER PRIMARY KEY, handle VARCHAR, "
            "display_name VARCHAR, description VARCHAR, credibility VARCHAR)"
        ))
        conn.execute(text(
            "CREATE TABLE domainaccount (domain_id INTEGER, account_id INTEGER)"
        ))

    _apply_migrations(engine)

    account_cols = _column_names(engine, "account")
    assert {"verified", "x_user_id", "last_fetched_at",
            "followers_count", "last_post_at"} <= account_cols
    assert "added_at" in _column_names(engine, "domainaccount")

    # Idempotent: a second run must not fail or duplicate columns.
    _apply_migrations(engine)
    assert _column_names(engine, "account") == account_cols


def test_migrations_noop_on_fresh_schema():
    import xscimon.models  # noqa: F401 — register all tables
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    before = _column_names(engine, "account")

    _apply_migrations(engine)
    assert _column_names(engine, "account") == before


def test_migrations_skip_missing_tables():
    # Empty database: create_all hasn't run — migrations must not invent tables.
    engine = create_engine("sqlite://")
    _apply_migrations(engine)
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).all()
    assert tables == []


def test_migrations_raise_on_real_errors(monkeypatch):
    # A genuine DDL failure must surface, not be swallowed like the old
    # blanket try/except did.
    from xscimon import database

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE account (id INTEGER PRIMARY KEY)"))

    monkeypatch.setattr(database, "_MIGRATIONS",
                        {"account": [("verified", "NOT_A_VALID_TYPE(((")]})
    with pytest.raises(Exception):
        database._apply_migrations(engine)

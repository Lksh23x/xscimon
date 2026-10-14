from pathlib import Path
from sqlalchemy import event, text
from sqlmodel import SQLModel, Session, create_engine
from .config import get_config

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        db_path = Path(get_config()["database"]["path"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: connections are shared between the APScheduler
        # thread and FastAPI's threadpool via the pool; SQLAlchemy serialises
        # access per connection, so pysqlite's thread affinity check is safe to
        # disable and would otherwise raise ProgrammingError.
        _engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            # WAL lets readers proceed while the pipeline writes.
            cursor.execute("PRAGMA journal_mode=WAL")
            # Wait up to 5s on a locked database instead of failing immediately.
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return _engine


# Columns added after the initial schema, applied to existing databases.
# Fresh databases get them from create_all, so only missing columns are altered.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "account": [
        ("verified", "BOOLEAN DEFAULT 1"),
        ("x_user_id", "VARCHAR"),
        ("last_fetched_at", "DATETIME"),
        ("followers_count", "INTEGER"),
        ("last_post_at", "DATETIME"),
    ],
    "domainaccount": [
        ("added_at", "DATETIME"),
    ],
    "fetchcoverage": [
        ("covered_from", "DATETIME"),
    ],
}


def _apply_migrations(engine) -> None:
    """Add missing columns by inspecting the live schema. Unlike a blanket
    try/except around ALTER TABLE, genuine failures (disk, corruption) raise."""
    with engine.begin() as conn:
        for table, columns in _MIGRATIONS.items():
            rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
            existing = {row[1] for row in rows}
            if not existing:
                continue  # table doesn't exist yet — create_all builds it complete
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db(engine=None) -> None:
    from . import models  # noqa: ensure all models are imported before create_all
    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    _apply_migrations(engine)


def get_session():
    with Session(get_engine()) as session:
        yield session

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from yaprr_api.settings import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_engine(url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate(engine_=None) -> str:
    """Bring the database to the latest Alembic revision (runs on API startup).

    - fresh DB              -> `upgrade head` creates everything
    - DB made by create_all -> (pre-Alembic dev DBs) add any missing columns, then `stamp head`
    - managed DB            -> `upgrade head` applies only the new migrations
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    engine_ = engine_ or engine
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    insp = inspect(engine_)
    legacy = insp.has_table("agents") and not insp.has_table("alembic_version")
    if legacy:
        import yaprr_api.models  # noqa: F401 - register every table on Base.metadata

        Base.metadata.create_all(engine_)  # tables added after the DB was made
        add_missing_columns(engine_)
    with engine_.begin() as conn:
        cfg.attributes["connection"] = conn  # migrate *this* engine, not the app default
        if legacy:
            command.stamp(cfg, "head")
            return "stamped"
        command.upgrade(cfg, "head")
    return "upgraded"


def add_missing_columns(engine_) -> list[str]:
    """Used once, to adopt pre-Alembic dev databases (see `migrate`)."""
    from sqlalchemy import inspect, text

    added = []
    insp = inspect(engine_)
    with engine_.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine_.dialect)}'))
                    added.append(f"{table.name}.{col.name}")
    return added

from __future__ import annotations

from alembic import context

import yaprr_api.models  # noqa: F401  (registers tables on Base.metadata)
from yaprr_api.db import Base, engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = context.config.attributes.get("connection") or engine
    if hasattr(connectable, "connect") and not hasattr(connectable, "execute"):
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()

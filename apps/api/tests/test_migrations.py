import sqlite3

from sqlalchemy import inspect

from yaprr_api.db import make_engine, migrate


def test_fresh_db_upgrades_and_legacy_db_is_adopted(tmp_path):
    fresh = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    assert migrate(fresh) == "upgraded"
    assert {"agents", "agent_versions", "calls", "alembic_version"} <= set(inspect(fresh).get_table_names())
    assert migrate(fresh) == "upgraded"  # idempotent

    legacy_path = tmp_path / "legacy.db"  # what create_all made before Alembic, minus a newer column
    con = sqlite3.connect(legacy_path)
    con.execute("create table agents (id varchar primary key, name varchar, status varchar, config json, "
                "published_version int, created_at datetime, updated_at datetime)")
    con.execute("create table calls (id varchar primary key, room_name varchar)")
    con.commit()
    con.close()
    legacy = make_engine(f"sqlite:///{legacy_path}")
    assert migrate(legacy) == "stamped"
    cols = {c["name"] for c in inspect(legacy).get_columns("calls")}
    assert "llm_failovers" in cols

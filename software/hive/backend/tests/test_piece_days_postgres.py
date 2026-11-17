"""The stats worker's kept answers on Postgres, through the real migration.

The suite runs on sqlite, where the triggers are sqlite's. These run the same
scenarios as test_piece_days.py on a throwaway Postgres database built by
`alembic upgrade head`, so the migration's triggers, the per-day SQL and the
full count of a machine's crops are what is checked. They run only when
HIVE_TEST_POSTGRES_URL names such a database (it is migrated and emptied here).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings

PG_URL = os.environ.get("HIVE_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set HIVE_TEST_POSTGRES_URL to a throwaway Postgres database")

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pg_engine():
    original = settings.DATABASE_URL
    settings.DATABASE_URL = PG_URL
    try:
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        command.upgrade(config, "head")
    finally:
        settings.DATABASE_URL = original
    engine = create_engine(PG_URL)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE users, machines, machine_piece_day_marks, machine_channel_crop_deltas, worker_state CASCADE"))
    session = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


from tests.test_piece_days import (  # noqa: E402, F401  (collected here with this module's db)
    owner,
    test_a_deleted_machine_leaves_nothing_behind,
    test_a_machine_from_before_the_triggers_is_counted_in_full_once,
    test_a_pass_reads_only_the_days_that_changed,
    test_crop_counts_follow_inserts_resends_and_deletes,
    test_fleet_mass_and_records_read_the_kept_numbers,
    test_numbers_follow_every_kind_of_change,
)

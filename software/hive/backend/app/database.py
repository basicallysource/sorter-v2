from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# Default pool (5 + 10 overflow = 15) is too tight once the teacher worker pool runs
# alongside normal web traffic. The worker briefly holds a session per item-claim + one
# per result-write across ``TEACHER_WORKER_PARALLELISM`` threads, plus FastAPI handlers
# grab their own. Raising the ceiling avoids the QueuePool timeouts we hit in prod.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,
    pool_recycle=1800,
    # Kill any query still running after 60s. Cloudflare returns 524 at 100s and
    # the browser retries, so without this a pathological query keeps executing
    # per retry and they pile up until Postgres starves (2026-07-16). Workers
    # that legitimately run longer must opt out per-connection
    # (SET statement_timeout = 0). A request gets a shorter one of its own
    # (STATEMENT_TIMEOUT_KEY below, set by app.deps.get_db).
    connect_args={"options": "-c statement_timeout=60000"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# A session whose ``info`` carries this (milliseconds) starts every transaction
# with SET LOCAL statement_timeout. LOCAL ends with the transaction, so the
# pooled connection goes back to the engine default for its next user, and a
# handler that commits halfway gets the same limit again on its next
# transaction. A no-op off Postgres (the tests).
STATEMENT_TIMEOUT_KEY = "statement_timeout_ms"


@event.listens_for(Session, "after_begin")
def _apply_statement_timeout(session: Session, _transaction, connection) -> None:
    timeout_ms = session.info.get(STATEMENT_TIMEOUT_KEY)
    if timeout_ms and connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")


def tune_for_aggregates(db, work_mem: str = "32MB") -> None:
    """Planner settings for the current transaction of a handler or worker pass
    that still sorts or aggregates.

    The server default work_mem (4 MB) makes a sort of a few hundred thousand
    rows spill to temp files on disk, and JIT compiles every plan whose cost
    estimate is high, which adds a fraction of a second to queries that finish
    in milliseconds. SET LOCAL ends with the transaction, so nothing leaks into
    the pooled connection's next user. A no-op off Postgres (the tests).
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    from sqlalchemy import text

    db.execute(text(f"SET LOCAL work_mem = '{work_mem}'"))
    db.execute(text("SET LOCAL jit = off"))

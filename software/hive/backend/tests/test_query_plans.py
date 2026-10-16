"""No request scans or sorts history: every list and count the API serves,
EXPLAINed on a production-sized database.

Each case below is a request a page of the UI (or an API client) makes, with
the filters a person can pick. The test sends it through the app, runs every
SELECT the code issues under EXPLAIN (ANALYZE, BUFFERS) in the request's own
transaction (so ``SET LOCAL`` tuning applies), and fails when a plan

  * reads a history table with a sequential scan,
  * reads more rows of history than the case's budget (rows a scan returned
    plus rows its filter threw away, over every scan of every history table in
    the statement; ``BUDGET`` unless the case says why it needs more), or
  * sorts, hashes or aggregates more than ``MAX_SORTED`` rows of history.

History is what machines write and what grows with every piece sorted (see
``HISTORY``). What people write (reviews, labels) grows at the speed of people
and may be counted directly.

It needs the database ``scripts/seed_large.py`` builds (production's shape and
size), so it runs only when HIVE_QUERY_PLAN_DB_URL names one; nothing it does
is committed. To also get a table of every case (time, rows read, plan shape)
set HIVE_QUERY_PLAN_REPORT to a file to append JSON lines to.

    HIVE_QUERY_PLAN_DB_URL=postgresql://... uv run pytest tests/test_query_plans.py
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import pytest

PLAN_DB_URL = os.environ.get("HIVE_QUERY_PLAN_DB_URL")
REPORT_PATH = os.environ.get("HIVE_QUERY_PLAN_REPORT")

pytestmark = pytest.mark.skipif(
    not PLAN_DB_URL, reason="set HIVE_QUERY_PLAN_DB_URL to a database scripts/seed_large.py built"
)

# --- The rules ---------------------------------------------------------------------

HISTORY = frozenset(
    {
        "samples",
        "sample_channel_geometry",
        "sample_swatch_runs",
        "sample_swatches",
        "model_dataset_samples",
        "teacher_job_items",
        "upload_sessions",
        "machine_pieces",
        "machine_piece_images",
        "machine_channel_crops",
        "machine_piece_predictions",
        "machine_piece_rejection_reasons",
        "machine_control_data_segments",
        "machine_training_runs",
        "piece_model_colors",
        "labeling_queue",
    }
)
# Not history: `jobs` holds the work in flight (done and failed jobs are
# pruned), and what people write (sample_reviews, piece_*_labels) grows at the
# speed of people.

# Rows of history one statement may read. A page of 60 that has to look at a
# few thousand rows to find them is fine; tens of thousands is a scan.
BUDGET = 3_000
# Rows of history a sort, hash or aggregate may take in.
MAX_SORTED = 5_000
# A reviewer sees their own machines and the newest pieces of everyone's, this
# many (access_window's default); reading that window is bounded by its size.
REVIEWER_WINDOW = 5_000


@dataclass(frozen=True)
class Case:
    """One request: what a person is looking at, and the request it makes.

    ``path`` may name {busy} (the machine with the most samples), {small} (an
    active machine with few), {member_machine}, {sample}, {piece_machine},
    {piece}, {trained_machine} and {trained_piece} (a piece a training run
    labelled), {old_color_model} (a colour model that is not the active one),
    {crop}, {old_crop}, {model}, {teacher_job} and {reviewer}: rows
    of the seeded fleet the fixture finds. ``pages`` follows next_cursor that many pages."""

    name: str
    path: str
    user: str = "admin"  # admin | reviewer | member | small_member
    method: str = "GET"
    body: dict | None = None
    pages: int = 1
    budget: int | None = BUDGET  # None: no limit on rows read (``why`` says why)
    max_sorted: int = MAX_SORTED
    why: str = ""  # why a case needs other limits than BUDGET and MAX_SORTED
    ok_status: tuple[int, ...] = (200,)


CROP_WINDOW = 50_000  # a reviewer's window of the newest crops (access_window's default)
CROP_RANK = (
    "whether a crop is in a reviewer's window of the newest crops is counted that far at most, through "
    "a BRIN index that reads whole block ranges: a few times the window"
)
DAY_OF_PIECES = "counts the last day of the fleet's pieces through (machine_id, seen_at): a day, not history"
PARTS_WINDOW = "the parts summary reads a machine's newest 20,000 pieces at most"

S = "/api/samples?limit=60"  # the Channel samples grid asks for 60 at a time
P = "/api/labeling/pieces?limit=60&with_candidates=true"  # the Piece samples grid

CASES: list[Case] = [
    # --- Channel samples: the grid, with each filter a person can pick ----------
    Case("samples: default view (teacher-checked, good light)", S, pages=2),
    Case("samples: raw and teacher-checked", S + "&annotated=all", pages=2),
    Case("samples: raw only", S + "&annotated=raw"),
    Case("samples: under-exposed", S + "&exposure=under"),
    Case("samples: over-exposed", S + "&exposure=over"),
    Case("samples: the busiest machine", S + "&machine_id={busy}", pages=2),
    Case("samples: a machine with few samples", S + "&machine_id={small}"),
    Case("samples: two machines", S + "&machine_id={busy}&machine_id={small}"),
    Case("samples: C4 classification channel", S + "&source_role=classification_channel"),
    Case("samples: top camera (older hardware)", S + "&source_role=top"),
    Case("samples: classification chamber", S + "&source_role=classification_chamber"),
    Case("samples: a common capture reason", S + "&capture_reason=rt_move_completed"),
    Case("samples: a rare capture reason", S + "&capture_reason=manual_capture"),
    Case("samples: accepted", S + "&review_status=accepted"),
    Case("samples: needs more reviews", S + "&review_status=in_review"),
    Case("samples: conflicts", S + "&review_status=conflict"),
    Case("samples: condition crops", S + "&kind=condition"),
    Case("samples: regular crops", S + "&kind=regular"),
    Case("samples: not reviewed by me", S + "&my_review=unreviewed"),
    Case("samples: reviewed by me", S + "&my_review=reviewed"),
    Case("samples: I accepted", S + "&my_review=accepted"),
    Case("samples: palette in view", S + "&palette=in_view"),
    Case("samples: palette not in view", S + "&palette=not_in_view"),
    Case("samples: palette not checked yet", S + "&palette=unchecked"),
    Case("samples: palette in view, raw too", S + "&palette=in_view&annotated=all"),
    Case("samples: last 24 hours", S + "&max_age_hours=24"),
    Case("samples: last 24 hours, raw too", S + "&max_age_hours=24&annotated=all"),
    Case("samples: archived (admin)", S + "&archived=archived"),
    Case("samples: archived and active (admin)", S + "&archived=all"),
    Case("samples: my machines (admin)", S + "&scope=mine"),
    Case("samples: a member's own machines", S, user="member"),
    Case("samples: a member, one machine", S + "&machine_id={member_machine}", user="member"),
    Case("samples: a member whose one machine is small", S, user="small_member"),
    Case("samples: a reviewer", S, user="reviewer"),
    Case("samples: small machine, top camera, raw too", S + "&machine_id={small}&source_role=top&annotated=all"),
    Case("samples: busiest machine, accepted", S + "&machine_id={busy}&review_status=accepted"),
    Case("samples: C2, raw too, last 7 days", S + "&source_role=c_channel_2&annotated=all&max_age_hours=168"),
    # --- The review page: the fresh work -------------------------------------------
    Case("review: fresh work", S + "&needs_review=true", pages=2),
    Case("review: fresh work, one machine", S + "&needs_review=true&machine_id={busy}"),
    Case("review: fresh work, a reviewer", S + "&needs_review=true", user="reviewer"),
    # --- What the samples pages load beside the grid -------------------------------
    Case("samples: filter options", "/api/samples/filter-options"),
    Case("samples: filter options, mine", "/api/samples/filter-options?scope=mine"),
    Case("dashboard: sample counts", "/api/stats/overview"),
    Case("samples header: counts for one machine", "/api/stats/overview?machine_id={busy}"),
    Case("samples: the machine picker", "/api/machines?scope=all"),
    Case("sample: detail", "/api/samples/{sample}"),
    Case("sample: review history", "/api/review/samples/{sample}/history"),
    Case("sample: swatch runs", "/api/samples/{sample}/swatch-runs"),
    Case(
        "sample: similar samples",
        "/api/samples/{sample}/similar?limit=48&max_distance=16",
        budget=None,
        why="Hamming distance has no index: it compares against every active sample's hash, "
        "from a narrow covering index (index-only), never the table",
    ),
    Case("diversity: every capture reason", "/api/samples/diversity"),
    Case("diversity: one capture reason", "/api/samples/diversity?capture_reason=rt_move_completed"),
    Case("diversity: my machines", "/api/samples/diversity?scope=mine"),
    Case(
        "samples: archive preview (dry run)",
        "/api/samples/batch-archive",
        method="POST",
        body={"dry_run": True, "annotated": "teacher", "exposure": "normal"},
        budget=45_000,
        max_sorted=25_000,
        why="a bulk action's preview counts what it would act on, as far as the action's cap (20,000)",
    ),
    Case(
        "samples: delete preview (dry run), a member",
        "/api/samples/batch-delete",
        method="POST",
        body={"dry_run": True, "annotated": "teacher", "exposure": "normal"},
        user="member",
        budget=30_000,
        max_sorted=10_000,
        why="a bulk action's preview counts what it would act on, as far as the action's cap (5,000)",
    ),
    # --- Piece samples: the labeling grid, each sort -------------------------------
    Case("pieces: priority", P + "&sort=priority", pages=2),
    Case("pieces: newest", P + "&sort=recent", pages=2),
    Case("pieces: oldest", P + "&sort=oldest"),
    Case("pieces: fewest colour labels", P + "&sort=least_color"),
    Case("pieces: fewest colour labels, a machine with training runs", P + "&sort=least_color&machine_id={trained_machine}"),
    Case(
        "pieces: most colour labels",
        P + "&sort=most_color",
        budget=10_000,
        why="orders the pieces people labeled by their labels: bounded by human work, not history",
    ),
    Case("pieces: fewest crop links", P + "&sort=least_crop"),
    Case("pieces: most crop links", P + "&sort=most_crop"),
    Case("pieces: fewest part labels", P + "&sort=least_part"),
    Case("pieces: most part labels", P + "&sort=most_part"),
    Case("pieces: likely a rare colour", P + "&sort=rare_color"),
    Case("pieces: unidentified", P + "&sort=unidentified"),
    Case("pieces: what I have not labeled", P + "&sort=needs_me"),
    Case("pieces: what I have not labeled, a machine with training runs", P + "&sort=needs_me&machine_id={trained_machine}"),
    Case("pieces: priority, one machine", P + "&sort=priority&machine_id={busy}"),
    Case("pieces: newest, a small machine", P + "&sort=recent&machine_id={small}"),
    Case("pieces: priority, with or without candidates", "/api/labeling/pieces?limit=60&sort=priority"),
    Case("pieces: palette in view near them", P + "&sort=priority&with_palette=true"),
    Case("pieces: newest, palette in view, one machine", P + "&sort=recent&with_palette=true&machine_id={busy}"),
    Case("pieces: least sure first, the active colour model", P + "&sort=least_sure", pages=2),
    Case("pieces: surest first, an older colour model", P + "&sort=surest&color_model={old_color_model}", pages=2),
    Case(
        "pieces: least sure first, one machine, palette in view",
        P + "&sort=least_sure&machine_id={busy}&with_palette=true",
        pages=2,
    ),
    Case("pieces: least sure first, two machines", P + "&sort=least_sure&machine_id={busy}&machine_id={small}"),
    Case("pieces: newest, with a colour model's answers", P + "&sort=recent&color_model={old_color_model}"),
    Case("pieces: least sure first, a member", P + "&sort=least_sure", user="member"),
    Case("pieces: the colour models", "/api/labeling/color-models"),
    Case(
        "pieces: priority, a reviewer",
        P + "&sort=priority",
        user="reviewer",
        budget=BUDGET + REVIEWER_WINDOW,
        why="a reviewer's window of the newest pieces is read to scope the page",
    ),
    Case("pieces: priority, a member", P + "&sort=priority", user="member"),
    Case("pieces: newest, a member whose one machine is small", P + "&sort=recent", user="small_member"),
    Case("pieces: labeling stats", "/api/labeling/stats"),
    Case("pieces: labeling stats, one machine", "/api/labeling/stats?machine_id={busy}"),
    Case(
        "pieces: labeling stats, a reviewer",
        "/api/labeling/stats",
        user="reviewer",
        budget=BUDGET + 2 * REVIEWER_WINDOW,
        why="counts within a reviewer's window of the newest pieces: bounded by the window",
    ),
    Case("pieces: colour coverage", "/api/labeling/color-coverage"),
    Case("piece: detail", "/api/labeling/piece/{piece_machine}/{piece}"),
    Case("piece: detail, a reviewer", "/api/labeling/piece/{piece_machine}/{piece}", user="reviewer"),
    Case("piece: detail, from a training run", "/api/labeling/piece/{trained_machine}/{trained_piece}"),
    Case("piece: same-piece candidates", "/api/labeling/possible-crops/{piece_machine}/{piece}"),
    Case(
        "piece: the machine's labeled reference column",
        "/api/labeling/machine/{piece_machine}/labeled-pieces?anchor_piece={piece}",
    ),
    Case(
        "piece: a crop image, a reviewer",
        "/api/labeling/pieces/{piece_machine}/{piece}/images/0",
        user="reviewer",
        ok_status=(200, 404),
    ),
    Case(
        "piece: a channel crop image, a reviewer",
        "/api/labeling/channel-crops/{piece_machine}/{crop}/image",
        user="reviewer",
        ok_status=(200, 404),
        budget=BUDGET + 3 * CROP_WINDOW,
        max_sorted=CROP_WINDOW,
        why=CROP_RANK,
    ),
    Case(
        "piece: a two-month-old channel crop, a reviewer",
        "/api/labeling/channel-crops/{piece_machine}/{old_crop}/image",
        user="reviewer",
        ok_status=(404,),
        budget=BUDGET + 3 * CROP_WINDOW,
        max_sorted=CROP_WINDOW,
        why=CROP_RANK,
    ),
    # --- Machines --------------------------------------------------------------
    Case("machines: my machines' stats", "/api/machines/stats"),
    Case("machine: overview", "/api/machines/{busy}/overview"),
    Case("machine: its pieces", "/api/machines/{busy}/pieces?limit=60", pages=2),
    Case("machine: its training runs", "/api/machines/{trained_machine}/training-runs?limit=4", pages=2),
    Case("machine: its channel crops", "/api/machines/{busy}/channel-crops?limit=120", pages=2),
    Case("machine: its C3 crops", "/api/machines/{busy}/channel-crops?limit=120&channel=3"),
    Case("machine: its crops at the exit", "/api/machines/{busy}/channel-crops?limit=120&zone_code=2"),
    Case("machine: a small machine's crops", "/api/machines/{small}/channel-crops?limit=120"),
    Case("admin: machines", "/api/admin/machines"),
    Case("admin: fleet stats", "/api/admin/machines/stats"),
    Case("analytics: the fleet", "/api/analytics?scope=all"),
    Case("analytics: one machine", "/api/analytics?machine_id={busy}"),
    Case("analytics: my machines", "/api/analytics?scope=mine"),
    # --- Leaderboard -------------------------------------------------------------
    Case("leaderboard: 24 hours", "/api/leaderboard?period=24h&limit=100"),
    Case("leaderboard: 7 days", "/api/leaderboard?period=7d&limit=100"),
    Case("leaderboard: 30 days", "/api/leaderboard?period=30d&limit=100"),
    Case("leaderboard: all time", "/api/leaderboard?period=all&limit=100"),
    Case("leaderboard: a reviewer's profile", "/api/leaderboard/{reviewer}"),
    # --- Public stats (website, Discord bot) ----------------------------------------
    Case("public: stats", "/api/public/stats", budget=25_000, max_sorted=25_000, why=DAY_OF_PIECES),
    Case("public: fleet", "/api/public/fleet", budget=25_000, max_sorted=25_000, why=DAY_OF_PIECES),
    Case("public: fleet, anonymous", "/api/public/fleet/anon", budget=25_000, max_sorted=25_000, why=DAY_OF_PIECES),
    Case("public: contributors", "/api/public/contributors"),
    Case("public: fleet records", "/api/public/fleet/records"),
    # --- Admin -------------------------------------------------------------------
    Case("admin: background jobs", "/api/admin/jobs"),
    Case("admin: teacher jobs", "/api/admin/teacher/jobs"),
    Case(
        "admin: a teacher job",
        "/api/admin/teacher/jobs/{teacher_job}",
        budget=8_000,
        max_sorted=8_000,
        why="one job's items: bounded by the job, which an admin sized",
    ),
    Case("admin: control data", "/api/admin/control-data/summary"),
    Case("admin: server health", "/api/admin/server-health"),
    Case("admin: the Server page", "/api/admin/server"),
    Case("models: list", "/api/models"),
    Case("model: its dataset's machines", "/api/models/{model}/dataset-machines"),
    # --- Records API (an assistant building a profile) -----------------------------
    Case("records: my machines", "/api/records/machines"),
    Case("records: a machine's parts", "/api/records/machines/{busy}/parts", budget=25_000, max_sorted=25_000, why=PARTS_WINDOW),
    Case(
        "records: a machine's parts, last 7 days",
        "/api/records/machines/{busy}/parts?since_days=7",
        budget=25_000,
        max_sorted=25_000,
        why=PARTS_WINDOW,
    ),
    Case("records: a machine's pieces", "/api/records/machines/{busy}/pieces?limit=200", pages=2),
    Case("records: a machine's pieces, 500 a page", "/api/records/machines/{busy}/pieces?limit=500", pages=2),
    Case("records: a machine's lots and runs", "/api/records/machines/{busy}/sorting-runs"),
    Case(
        "records: an admin adds a run's predictions",
        "/api/records/machines/{busy}/predictions",
        method="POST",
        body={
            "source": "query plan check", "provider": "test", "model_name": "check", "kind": "color",
            "pieces": [{"piece_uuid": f"no-such-piece-{i}", "answers": [{"value_id": "11"}]} for i in range(1000)],
        },
        budget=20_000,
        why=(
            "an import names at most 1,000 pieces, looked up through the (machine, piece) index; for a machine with "
            "a few thousand pieces the planner reads its whole range of the index instead of 1,000 probes"
        ),
    ),
    Case(
        "records: a machine's pieces, last day",
        "/api/records/machines/{busy}/pieces?limit=200&since_days=1",
        budget=6_000,
        why="a page of the pieces list looks at its newest 5,000 pieces at most",
    ),
]


# --- Reading a plan ----------------------------------------------------------------

_SCANS = {"Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan", "Tid Scan", "Tid Range Scan"}
_TAKES_ALL = {"Sort", "Incremental Sort", "Aggregate", "Unique", "SetOp", "WindowAgg"}


@dataclass
class Statement:
    sql: str
    plan: dict
    ms: float = 0.0
    rows_read: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    shape: list[str] = field(default_factory=list)


def _loops(node: dict) -> int:
    return max(1, int(node.get("Actual Loops", 1) or 1))


def _rows(node: dict) -> int:
    return int(node.get("Actual Rows", 0) or 0) * _loops(node)


def _reads_history(node: dict) -> bool:
    if node.get("Node Type") in _SCANS and node.get("Relation Name") in HISTORY:
        return True
    return any(_reads_history(child) for child in node.get("Plans", []))


def judge(statement: Statement, budget: int | None, max_sorted: int = MAX_SORTED) -> None:
    """Fill in what a statement read and which rules it broke."""

    def walk(node: dict, depth: int) -> None:
        kind = node.get("Node Type", "?")
        table = node.get("Relation Name")
        label = kind + (f" {node['Index Name']}" if node.get("Index Name") else "") + (f" on {table}" if table else "")
        if kind in _SCANS and table in HISTORY:
            read = (
                _rows(node)
                + int(node.get("Rows Removed by Filter", 0) or 0) * _loops(node)
                + int(node.get("Rows Removed by Index Recheck", 0) or 0) * _loops(node)
            )
            statement.rows_read[table] = statement.rows_read.get(table, 0) + read
            statement.shape.append(f"{'  ' * depth}{label}: read {read:,}")
            if kind == "Seq Scan":
                statement.problems.append(f"sequential scan of {table} ({read:,} rows)")
        elif kind in _TAKES_ALL or kind in {"Hash", "HashAggregate", "GroupAggregate"}:
            taken = _rows(node) if kind == "Hash" else sum(_rows(c) for c in node.get("Plans", []))
            if _reads_history(node):
                statement.shape.append(f"{'  ' * depth}{label}: takes {taken:,}")
                if taken > max_sorted:
                    statement.problems.append(f"{kind} of {taken:,} rows of history (more than {max_sorted:,})")
        for child in node.get("Plans", []):
            walk(child, depth + 1)

    walk(statement.plan["Plan"], 0)
    statement.ms = float(statement.plan.get("Execution Time", 0.0))
    total = sum(statement.rows_read.values())
    if budget is not None and total > budget:
        per_table = ", ".join(f"{t} {n:,}" for t, n in sorted(statement.rows_read.items()))
        statement.problems.append(f"reads {total:,} rows of history, budget {budget:,} ({per_table})")


# --- Running a case ----------------------------------------------------------------


@pytest.fixture(scope="module")
def plan_engine():
    from sqlalchemy import create_engine

    engine = create_engine(PLAN_DB_URL, connect_args={"options": "-c statement_timeout=300000"})
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def fleet(plan_engine) -> dict[str, Any]:
    """Rows of the seeded fleet the cases name: found by what they are, so the
    test reads any production-shaped database, not only the seeded one."""
    from sqlalchemy import text

    queries = {
        "admin": "SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY created_at LIMIT 1",
        "reviewer": """SELECT u.id FROM users u WHERE u.role = 'reviewer' AND u.is_active
                       ORDER BY (SELECT count(*) FROM piece_color_labels l WHERE l.labeler_id = u.id) DESC LIMIT 1""",
        "member": """SELECT m.owner_id FROM machines m JOIN users u ON u.id = m.owner_id
                     JOIN machine_stats_cache c ON c.machine_id = m.id
                     WHERE u.role = 'member' AND m.archived_at IS NULL
                     GROUP BY m.owner_id ORDER BY sum(c.total_samples) DESC LIMIT 1""",
        "busy": """SELECT m.id FROM machines m JOIN machine_stats_cache c ON c.machine_id = m.id
                   WHERE m.archived_at IS NULL ORDER BY c.total_samples DESC LIMIT 1""",
        "small": """SELECT m.id FROM machines m JOIN machine_stats_cache c ON c.machine_id = m.id
                    WHERE m.archived_at IS NULL AND c.total_samples > 0 AND c.pieces_seen > 0
                    ORDER BY c.total_samples LIMIT 1""",
        "teacher_job": "SELECT id FROM teacher_jobs ORDER BY created_at DESC LIMIT 1",
        "old_color_model": "SELECT sha256 FROM color_models WHERE NOT is_active ORDER BY created_at DESC LIMIT 1",
        "model": """SELECT id FROM detection_models d
                    WHERE EXISTS (SELECT 1 FROM model_dataset_samples s WHERE s.model_id = d.id)
                    ORDER BY published_at DESC LIMIT 1""",
    }
    with plan_engine.connect() as conn:
        ids = {name: conn.execute(text(sql)).scalar() for name, sql in queries.items()}
        # A member whose only machine is a small one: their pages must not read
        # the fleet's to find it.
        ids["small_member"] = conn.execute(
            text(
                """SELECT m.owner_id FROM machines m JOIN users u ON u.id = m.owner_id
                   WHERE m.id = :small AND u.role = 'member'
                     AND (SELECT count(*) FROM machines o WHERE o.owner_id = m.owner_id) = 1"""
            ),
            {"small": ids["small"]},
        ).scalar()
        ids["member_machine"] = conn.execute(
            text(
                """SELECT m.id FROM machines m JOIN machine_stats_cache c ON c.machine_id = m.id
                   WHERE m.owner_id = :owner AND m.archived_at IS NULL ORDER BY c.total_samples DESC LIMIT 1"""
            ),
            {"owner": ids["member"]},
        ).scalar()
        ids["sample"] = conn.execute(
            text(
                """SELECT id FROM samples WHERE machine_id = :m AND archived_at IS NULL
                   AND (extra_metadata -> 'teacher_rerun') IS NOT NULL ORDER BY uploaded_at DESC LIMIT 1"""
            ),
            {"m": ids["busy"]},
        ).scalar()
        piece = conn.execute(
            text(
                """SELECT q.machine_id, q.piece_uuid FROM labeling_queue q
                   WHERE q.machine_id = :m AND q.has_candidates AND q.arrival_at < now() - interval '1 hour'
                   ORDER BY q.machine_id, q.arrival_at DESC LIMIT 1"""
            ),
            {"m": ids["busy"]},
        ).one()
        ids["piece_machine"], ids["piece"] = piece
        # The newest piece a training run labelled, on the machine with the most.
        trained = conn.execute(
            text(
                """SELECT q.machine_id, q.piece_uuid FROM labeling_queue q
                   WHERE q.has_training_label AND q.machine_id = (
                       SELECT machine_id FROM machine_training_runs GROUP BY machine_id ORDER BY sum(piece_count) DESC LIMIT 1)
                   ORDER BY q.arrival_at DESC LIMIT 1"""
            )
        ).one()
        ids["trained_machine"], ids["trained_piece"] = trained
        # A crop the piece's labeling page shows (seconds before it arrived),
        # and one from two months ago.
        ids["crop"] = conn.execute(
            text(
                """SELECT c.local_id FROM machine_pieces p JOIN machine_channel_crops c
                     ON c.machine_id = p.machine_id
                    AND c.ts BETWEEN coalesce(p.seen_at, p.created_at) - interval '60 seconds'
                                 AND coalesce(p.seen_at, p.created_at)
                   WHERE p.machine_id = :m AND p.piece_uuid = :p ORDER BY c.ts DESC LIMIT 1"""
            ),
            {"m": ids["piece_machine"], "p": ids["piece"]},
        ).scalar()
        ids["old_crop"] = conn.execute(
            text(
                """SELECT local_id FROM machine_channel_crops WHERE machine_id = :m
                   AND ts < now() - interval '60 days' ORDER BY machine_id, ts DESC LIMIT 1"""
            ),
            {"m": ids["piece_machine"]},
        ).scalar()
        roles = {
            ids[who]: conn.execute(text("SELECT role FROM users WHERE id = :id"), {"id": ids[who]}).scalar()
            for who in ("admin", "reviewer", "member", "small_member")
        }
    missing = [name for name, value in ids.items() if value is None]
    assert not missing, f"the database has no {missing}: build it with scripts/seed_large.py"
    ids["roles"] = roles
    return ids


@pytest.fixture()
def run_case(plan_engine, fleet, monkeypatch):
    """Send a case through the app on one connection, EXPLAIN every SELECT
    it runs in place, and roll everything back."""
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from app.deps import get_db
    from app.main import app
    from app.routers import public_stats
    from app.services import rate_limit
    from app.services.auth import create_access_token

    # Rate limits would turn the later cases into 429s.
    monkeypatch.setattr(rate_limit, "LIMITS", {k: {r: None for r in v} for k, v in rate_limit.LIMITS.items()})
    monkeypatch.setattr(app.state.limiter, "enabled", False)

    def run(case: Case) -> tuple[list[Statement], list[tuple[str, int, float]]]:
        connection = plan_engine.connect()
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
        statements: list[Statement] = []

        def explain(conn, cursor, sql, params, context, executemany):
            if executemany or sql.lstrip().split(None, 1)[0].upper() not in ("SELECT", "WITH"):
                return
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
            statements.append(Statement(sql=sql, plan=cursor.fetchone()[0][0]))

        def override_db():
            yield session

        event.listen(connection, "before_cursor_execute", explain)
        app.dependency_overrides[get_db] = override_db
        for dependency in (
            public_stats.require_stats_key,
            public_stats.require_fleet_key,
            public_stats.require_fleet_anon_key,
            public_stats.require_contributors_key,
        ):
            app.dependency_overrides[dependency] = lambda: None
        user_id = fleet[case.user]
        csrf = secrets.token_urlsafe(16)
        client = TestClient(app)
        client.cookies.set("access_token", create_access_token(str(user_id), fleet["roles"][user_id]))
        client.cookies.set("csrf_token", csrf)
        requests: list[tuple[str, int, float]] = []
        try:
            path = case.path.format(**{k: v for k, v in fleet.items() if k != "roles"})
            cursor = None
            for _ in range(case.pages):
                url = path if cursor is None else path + ("&" if "?" in path else "?") + urlencode({"cursor": cursor})
                started = time.monotonic()
                if case.method == "GET":
                    response = client.get(url)
                else:
                    response = client.request(case.method, url, json=case.body, headers={"X-CSRF-Token": csrf})
                requests.append((url, response.status_code, (time.monotonic() - started) * 1000))
                assert response.status_code in case.ok_status, f"{url}: {response.status_code} {response.text[:500]}"
                body = response.json() if response.status_code == 200 else None
                cursor = body.get("next_cursor") if isinstance(body, dict) else None
                if cursor is None:
                    break
        finally:
            event.remove(connection, "before_cursor_execute", explain)
            app.dependency_overrides.clear()
            session.close()
            outer.rollback()
            connection.close()
        return statements, requests

    return run


def _report(case: Case, statements: list[Statement], requests: list[tuple[str, int, float]]) -> None:
    if not REPORT_PATH:
        return
    with open(REPORT_PATH, "a") as f:
        f.write(
            json.dumps(
                {
                    "case": case.name,
                    "path": case.path,
                    "user": case.user,
                    "requests": [{"url": u, "status": s, "ms": round(ms, 1)} for u, s, ms in requests],
                    "statements": [
                        {
                            "sql": " ".join(st.sql.split())[:300],
                            "ms": round(st.ms, 2),
                            "rows_read": st.rows_read,
                            "shape": st.shape,
                            "problems": st.problems,
                        }
                        for st in statements
                    ],
                }
            )
            + "\n"
        )


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_plan_stays_within_budget(case: Case, run_case) -> None:
    statements, requests = run_case(case)
    for statement in statements:
        judge(statement, case.budget, case.max_sorted)
    _report(case, statements, requests)
    broken = [s for s in statements if s.problems]
    if broken:
        lines = [f"{case.name}: {case.path}"]
        for s in broken:
            lines.append("")
            lines.append(" ".join(s.sql.split())[:400])
            lines.extend(f"  ! {p}" for p in s.problems)
            lines.extend(f"    {row}" for row in s.shape)
        pytest.fail("\n".join(lines), pytrace=False)

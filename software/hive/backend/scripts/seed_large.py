"""A production-sized synthetic Hive database, for query-plan work.

Fills a freshly migrated, EMPTY Postgres database with a fleet shaped like
production's (October 2026): about 650k training samples, 1M sorted pieces with
3M piece crops and 9M upstream channel crops, a few thousand human labels and
reviews, swatch runs, background jobs, 30 machines and 50 users. Then it runs
the workers' first passes (the labeling queue, the per-machine stats) the way a
running Hive would have, and VACUUM ANALYZE. ``tests/test_query_plans.py``
EXPLAINs the API's list and count queries against the result.

Every row is generated inside Postgres from hashes of a row number, so two runs
build the same rows. Times are relative to the moment it runs (the newest rows
are minutes old), so "the last 24 hours" always has data.

    cd software/hive/backend
    export DATABASE_URL=postgresql://USER@HOST:PORT/DB   # a throwaway database
    uv run alembic upgrade heads
    uv run python -m scripts.seed_large                  # --scale 0.02 for a quick one

At scale 1 it takes about 25 minutes on two cores and 8 GB of disk; most of
the time is the labeling queue worker's first pass. It refuses to run on a
database that already has users, machines or samples.

What matters for query plans, and so is shaped like production:

  * Rows arrive in time order and faster as the fleet grows (the newest day
    holds about four times the rows of the oldest), so every table's physical
    order follows its timestamps, as it does on a database that only appends.
  * A few machines have most of the data; most machines have very little.
  * Samples change with the hardware: the oldest 40% are classification
    chamber, top, bottom and carousel frames; the rest mostly C-channel frames.
    A filter on an old source role therefore matches nothing among the newest
    rows, which is what makes a newest-first walk with that filter read the
    whole recent history before it finds a match.
  * About a third of samples older than two weeks were checked by the teacher
    (``extra_metadata.teacher_rerun``); almost none of the newest 14% were,
    which is what production looked like when the samples list timed out.
  * Exposure: about a fifth under-exposed, a few percent over-exposed.
  * Swatch runs exist for the classification channel samples of the last day
    and a scattering of older ones; a backfill of swatch jobs is queued.
  * Upstream channel crops (12 per piece) exist only for the newest 80% of
    pieces, as the feature arrived later; a piece's crops are timed in the
    seconds before it reached the classification channel.
  * The three busiest machines ran colour training runs of about an hour
    every few days over the last month, one still collecting; the pieces they
    saw then carry the run's colour labels.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass

import psycopg2

from app.config import settings

log = logging.getLogger("seed_large")

# How the rows of one table spread over the machines (machine 1 has the most).
# The first ten carry 95%; the other twenty are machines that sorted a little.
MACHINE_WEIGHTS = [0.30, 0.18, 0.12, 0.09, 0.07, 0.05, 0.04, 0.03, 0.03, 0.02] + [0.05 / 20] * 20

# Machine i belongs to user OWNERS[i - 1]. Users 1-2 are admins, 3-8 reviewers,
# the rest members. Admin 1 owns three of the busy machines; member 9 owns
# machine 4 (a member with a lot of data), member 10 machine 6.
OWNERS = [1, 1, 3, 9, 1, 10, 11, 12, 2, 13] + [14 + (i % 30) for i in range(20)]
ARCHIVED_MACHINES = {29, 30}

USERS = 50
ADMINS = 2
REVIEWERS = 6  # users 3-8
LABELERS = 14  # users 1-14 review and label

SWATCH_MODEL_ACTIVE = "a" * 64
SWATCH_MODEL_OLD = "b" * 64


@dataclass(frozen=True)
class Sizes:
    samples: int
    pieces: int
    days: int = 150

    @classmethod
    def at(cls, scale: float) -> "Sizes":
        return cls(samples=max(2000, int(650_000 * scale)), pieces=max(3000, int(1_000_000 * scale)))


SESSION_SETUP = """
SET statement_timeout = 0;
SET synchronous_commit = off;
SET max_parallel_workers_per_gather = 0;
SET work_mem = '256MB';
SET maintenance_work_mem = '512MB';
SET TIME ZONE 'UTC';
-- A table scan returns rows in the order they were written, so rows derived
-- from another table come out in its time order without a sort.
SET synchronize_seqscans = off;

-- A uniform number in [0, 1) from a row number and a salt: the same every run.
CREATE FUNCTION pg_temp.rnd(g bigint, salt int) RETURNS float8
LANGUAGE sql IMMUTABLE AS
$$ SELECT (hashint8extended(g, salt) & 9007199254740991)::float8 / 9007199254740992.0 $$;

-- A standard normal number (Box-Muller over two of the above).
CREATE FUNCTION pg_temp.gauss(g bigint, salt int) RETURNS float8
LANGUAGE sql IMMUTABLE AS
$$ SELECT sqrt(-2 * ln(1 - pg_temp.rnd(g, salt))) * cos(2 * pi() * pg_temp.rnd(g, salt + 1000)) $$;

-- Where row fraction x in [0, 1] falls in time, as a fraction of the span,
-- when the rate grows linearly to (1 + k) times its start.
CREATE FUNCTION pg_temp.ramp(x float8, k float8) RETURNS float8
LANGUAGE sql IMMUTABLE AS
$$ SELECT (-1 + sqrt(1 + 2 * k * x * (1 + k / 2))) / k $$;
"""


def _cum(weights: list[float]) -> list[float]:
    """Thresholds for width_bucket: [0, w1, w1+w2, ...] over normalised weights."""
    total = sum(weights)
    out, acc = [0.0], 0.0
    for w in weights[:-1]:
        acc += w / total
        out.append(acc)
    return out


class Seeder:
    def __init__(self, conn, sizes: Sizes):
        self.conn = conn
        self.cur = conn.cursor()
        self.sizes = sizes

    def run(self, sql: str, params: dict | None = None, what: str | None = None) -> None:
        started = time.monotonic()
        self.cur.execute(sql, params or {})
        self.conn.commit()
        if what:
            log.info("%s (%.0f s)", what, time.monotonic() - started)

    def count(self, table: str) -> int:
        self.cur.execute(f"SELECT count(*) FROM {table}")
        return int(self.cur.fetchone()[0])

    # --- Bulk loading without maintaining indexes row by row -----------------

    def detach(self, table: str) -> list[str]:
        """Drop a table's indexes and the constraints no other table depends
        on, and return the statements that put them back as they were."""
        cur = self.cur
        cur.execute(
            "SELECT conindid FROM pg_constraint WHERE confrelid = %s::regclass AND contype = 'f'", (table,)
        )
        kept_indexes = {row[0] for row in cur.fetchall()}
        cur.execute(
            """SELECT conname, pg_get_constraintdef(oid), contype, conindid FROM pg_constraint
               WHERE conrelid = %s::regclass AND contype IN ('p', 'u', 'f')""",
            (table,),
        )
        constraints = [row for row in cur.fetchall() if row[3] not in kept_indexes]
        backing = {row[3] for row in constraints} | kept_indexes
        cur.execute(
            """SELECT i.indexrelid, pg_get_indexdef(i.indexrelid), c.relname FROM pg_index i
               JOIN pg_class c ON c.oid = i.indexrelid WHERE i.indrelid = %s::regclass""",
            (table,),
        )
        indexes = [row for row in cur.fetchall() if row[0] not in backing and row[0] not in kept_indexes]
        restore = []
        # Keys first (an index build reads the table once), foreign keys last.
        for name, definition, kind, _ in sorted(constraints, key=lambda r: r[2] == "f"):
            cur.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
            restore.append(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" {definition}')
        for _, definition, name in indexes:
            cur.execute(f'DROP INDEX "{name}"')
            restore.insert(len([r for r in restore if "FOREIGN KEY" not in r]), definition)
        self.conn.commit()
        return restore

    def attach(self, table: str, restore: list[str]) -> None:
        started = time.monotonic()
        for statement in restore:
            self.cur.execute(statement)
            self.conn.commit()
        log.info("%s: %d indexes and constraints rebuilt (%.0f s)", table, len(restore), time.monotonic() - started)

    def load(self, table: str, sql: str, params: dict | None = None) -> None:
        restore = self.detach(table)
        self.run(sql, params)
        log.info("%s: %d rows", table, self.count(table))
        self.attach(table, restore)

    # --- The fleet --------------------------------------------------------------

    def refuse_unless_empty(self) -> None:
        for table in ("users", "machines", "samples", "machine_pieces"):
            if self.count(table):
                raise SystemExit(f"{table} is not empty: seed_large only fills a new, empty database.")

    def people_and_machines(self) -> None:
        self.run(
            """
            INSERT INTO users (id, email, password_hash, display_name, role, is_active, created_at, updated_at,
                               share_activity)
            SELECT md5('user:' || i)::uuid, 'user' || i || '@example.com', NULL, 'User ' || i,
                   CASE WHEN i <= %(admins)s THEN 'admin' WHEN i <= %(admins)s + %(reviewers)s THEN 'reviewer'
                        ELSE 'member' END,
                   true, now() - (%(days)s + 30 - i) * interval '1 day', now(), i %% 3 = 0
            FROM generate_series(1, %(users)s) i
            """,
            {"admins": ADMINS, "reviewers": REVIEWERS, "users": USERS, "days": self.sizes.days},
        )
        self.run(
            """
            CREATE TEMP TABLE seed_machines AS
            SELECT i, md5('machine:' || i)::uuid AS id, md5('user:' || (%(owners)s::int[])[i])::uuid AS owner_id
            FROM generate_series(1, %(n)s) i
            """,
            {"owners": OWNERS, "n": len(MACHINE_WEIGHTS)},
        )
        self.run(
            """
            INSERT INTO machines (id, owner_id, token_hash, token_prefix, name, description, hardware_info,
                                  last_seen_at, is_active, created_at, last_seen_ip, archived_at)
            SELECT id, owner_id, 'not-a-token', lpad(i::text, 8, 'm'), 'Machine ' || i, NULL,
                   jsonb_build_object('board', 'synthetic', 'cameras', 4),
                   -- The busiest seven report every minute; the rest went quiet days or weeks ago.
                   CASE WHEN i <= 7 THEN now() - i * interval '1 minute' ELSE now() - i * interval '2 days' END,
                   true, now() - (%(days)s + 5) * interval '1 day', '10.0.0.' || i,
                   CASE WHEN i = ANY(%(archived)s) THEN now() - interval '20 days' END
            FROM seed_machines
            """,
            {"days": self.sizes.days, "archived": sorted(ARCHIVED_MACHINES)},
        )
        # One upload session per machine and day.
        self.run(
            """
            INSERT INTO upload_sessions (id, machine_id, source_session_id, name, created_at, last_upload_at,
                                         sample_count)
            SELECT md5('session:' || m.i || ':' || d)::uuid, m.id, 'session-' || m.i || '-' || d, NULL,
                   date_trunc('day', now()) - d * interval '1 day', NULL, 0
            FROM seed_machines m, generate_series(0, %(days)s + 1) d
            """,
            {"days": self.sizes.days},
        )

    def samples(self) -> None:
        n = self.sizes.samples
        self.load(
            "samples",
            """
            INSERT INTO samples (id, machine_id, upload_session_id, local_sample_id, source_role, capture_reason,
                captured_at, image_path, full_frame_path, overlay_path, image_width, image_height,
                detection_algorithm, detection_bboxes, detection_count, detection_score, review_status,
                review_count, accepted_count, rejected_count, uploaded_at, resolved_at, extra_metadata,
                sample_payload, archived_at, phash, luminance_mean, luminance_p05, luminance_p95,
                clipped_low_ratio, clipped_high_ratio)
            SELECT md5('sample:' || g)::uuid, m.id,
                   md5('session:' || m.i || ':' || (current_date - t.at::date))::uuid,
                   's' || g, r.role, r.reason, t.at - interval '20 seconds',
                   'samples/' || m.i || '/' || g || '.jpg',
                   CASE WHEN r.full_frame THEN 'samples/' || m.i || '/' || g || '.jpg' END,
                   NULL, 3840, 2160, CASE WHEN f.teacher THEN 'gemini_sam' ELSE 'sorter_yolo' END,
                   d.boxes, d.n, CASE WHEN d.n > 0 THEN 0.5 + pg_temp.rnd(g, 9) / 2 END,
                   'unreviewed', 0, 0, 0, t.at, NULL,
                   jsonb_build_object(
                       'camera', jsonb_build_object('name', r.role, 'exposure_us', 4000 + (pg_temp.rnd(g, 10) * 8000)::int,
                                                    'gain', round((1 + pg_temp.rnd(g, 11) * 3)::numeric, 2),
                                                    'width', 3840, 'height', 2160, 'serial', left(md5('cam:' || m.i), 12)),
                       'lamp', jsonb_build_object('brightness', round(pg_temp.rnd(g, 12)::numeric, 2), 'mode', 'on'),
                       'software', jsonb_build_object('version', '0.4.' || (t.x * 6)::int, 'commit', left(md5('v' || (t.x * 6)::int), 8)),
                       'run_id', left(md5('run:' || m.i || ':' || t.at::date), 16),
                       'piece_uuid', md5('piece-uuid:' || g)::uuid::text,
                       'detection_scope', 'channel')
                   || CASE WHEN f.teacher THEN jsonb_build_object('teacher_rerun', jsonb_build_object(
                           'model', 'google/gemini-2.5-flash', 'generated_at', t.at + interval '3 days',
                           'count', d.n, 'score', 0.9, 'source', 'hive_teacher_worker',
                           'job_id', md5('teacher-job:' || (g %% 7))::uuid::text)) ELSE '{}'::jsonb END,
                   jsonb_build_object(
                       'version', 2,
                       'sample', jsonb_build_object('source_session_id', 'session-' || m.i, 'local_sample_id', 's' || g,
                                                    'source_role', r.role, 'capture_reason', r.reason,
                                                    'captured_at', t.at, 'machine_id', m.id, 'preferred_view', r.role),
                       'assets', jsonb_build_object('image', jsonb_build_object('path', 'samples/' || m.i || '/' || g || '.jpg',
                                                                              'content_type', 'image/jpeg')),
                       'analyses', jsonb_build_array(jsonb_build_object(
                           'kind', 'detection', 'algorithm', 'sorter_yolo',
                           'outputs', jsonb_build_object('found', d.n > 0, 'boxes', coalesce(d.boxes, '[]'::jsonb))))),
                   CASE WHEN f.archived THEN least(now(), t.at + interval '20 days') END,
                   CASE WHEN pg_temp.rnd(g, 13) >= 0.02 THEN hashint8extended(g, 14) END,
                   e.lum, greatest(0, e.lum - 60), least(255, e.lum + 60), e.low, e.high
            FROM generate_series(1, %(n)s) g
            CROSS JOIN LATERAL (
                SELECT ((g - 0.5) / %(n)s)::float8 AS x,
                       now() - %(days)s * interval '1 day' * (1 - pg_temp.ramp(((g - 0.5) / %(n)s)::float8, 3))
                           + (pg_temp.rnd(g, 1) - 0.5) * interval '20 seconds' AS at
            ) t
            CROSS JOIN LATERAL (
                SELECT i, md5('machine:' || i)::uuid AS id
                FROM width_bucket(pg_temp.rnd(g, 2), %(machine_cum)s::float8[]) i
            ) m
            CROSS JOIN LATERAL (
                SELECT CASE WHEN t.x >= 0.4 THEN
                            (ARRAY['classification_channel', 'c_channel_2', 'c_channel_3', 'classification_chamber', 'piece_crop'])
                            [width_bucket(pg_temp.rnd(g, 3), ARRAY[0, 0.5, 0.7, 0.9, 0.95])]
                       ELSE (ARRAY['classification_chamber', 'top', 'bottom', 'carousel', 'piece_crop'])
                            [width_bucket(pg_temp.rnd(g, 3), ARRAY[0, 0.45, 0.6, 0.75, 0.9])]
                       END AS role
            ) ro
            CROSS JOIN LATERAL (
                SELECT ro.role,
                       CASE ro.role
                         WHEN 'classification_channel' THEN
                           (ARRAY['rt_move_completed', 'live_classification', 'interval', 'standalone_sample_collection'])
                           [width_bucket(pg_temp.rnd(g, 4), ARRAY[0, 0.5, 0.8, 0.95])]
                         WHEN 'c_channel_2' THEN (ARRAY['channel_move_complete', 'interval', 'piece_condition_collector'])
                           [width_bucket(pg_temp.rnd(g, 4), ARRAY[0, 0.6, 0.9])]
                         WHEN 'c_channel_3' THEN (ARRAY['channel_move_complete', 'interval', 'piece_condition_collector'])
                           [width_bucket(pg_temp.rnd(g, 4), ARRAY[0, 0.6, 0.9])]
                         WHEN 'classification_chamber' THEN
                           (ARRAY['live_classification', 'interval', 'manual_capture', 'piece_condition_teacher'])
                           [width_bucket(pg_temp.rnd(g, 4), ARRAY[0, 0.6, 0.9, 0.95])]
                         WHEN 'carousel' THEN 'carousel_snap'
                         WHEN 'piece_crop' THEN 'piece_condition_collector'
                         ELSE 'live_classification'
                       END AS reason,
                       t.x >= 0.4 AND ro.role IN ('classification_channel', 'c_channel_2', 'c_channel_3') AS full_frame
            ) r
            CROSS JOIN LATERAL (
                SELECT pg_temp.rnd(g, 5) < CASE WHEN t.x < 0.86 THEN 0.35 ELSE 0.003 END AS teacher,
                       t.x < 0.5 AND pg_temp.rnd(g, 6) < 0.10 AS archived
            ) f
            CROSS JOIN LATERAL (
                SELECT least(14, floor(-ln(1 - pg_temp.rnd(g, 7)) * 2.2))::int AS n
            ) dn
            CROSS JOIN LATERAL (
                SELECT dn.n,
                       (SELECT jsonb_agg(jsonb_build_array(x0, y0, x0 + 40 + (b * 13) %% 90, y0 + 40 + (b * 29) %% 90))
                        FROM generate_series(1, dn.n) b,
                             LATERAL (SELECT (pg_temp.rnd(g * 16 + b, 8) * 3700)::int AS x0,
                                             (pg_temp.rnd(g * 16 + b, 18) * 2000)::int AS y0) p) AS boxes
            ) d
            CROSS JOIN LATERAL (
                SELECT CASE WHEN t.x < 0.3 AND pg_temp.rnd(g, 15) < 0.02 THEN NULL
                            ELSE least(250, greatest(5, 150 + 35 * pg_temp.gauss(g, 16))) END AS lum,
                       power(pg_temp.rnd(g, 17), 8) AS low,
                       power(pg_temp.rnd(g, 19), 12) AS high
            ) e
            """,
            {"n": n, "days": self.sizes.days, "machine_cum": _cum(MACHINE_WEIGHTS)},
        )
        self.run(
            """
            UPDATE upload_sessions u SET sample_count = c.n, last_upload_at = c.last
            FROM (SELECT upload_session_id, count(*) AS n, max(uploaded_at) AS last FROM samples
                  GROUP BY upload_session_id) c
            WHERE u.id = c.upload_session_id
            """
        )
        self.run("DELETE FROM upload_sessions WHERE sample_count = 0", what="upload sessions")

    def reviews(self) -> None:
        """Three reviews settle a sample. About 8% of the teacher-checked,
        active samples have one to three reviews from the labelers."""
        self.load(
            "sample_reviews",
            """
            INSERT INTO sample_reviews (id, sample_id, reviewer_id, decision, notes, created_at, updated_at)
            SELECT md5('review:' || s.g || ':' || j)::uuid, s.id,
                   md5('user:' || (1 + ((s.g * 7 + j * 5) %% %(labelers)s)))::uuid,
                   CASE WHEN pg_temp.rnd(s.g * 4 + j, 21) < 0.8 THEN 'accept' ELSE 'reject' END, NULL,
                   least(now(), s.uploaded_at + (3 + j) * interval '1 day'),
                   least(now(), s.uploaded_at + (3 + j) * interval '1 day')
            FROM (SELECT id, uploaded_at, substr(local_sample_id, 2)::bigint AS g FROM samples
                  WHERE archived_at IS NULL AND extra_metadata ? 'teacher_rerun') s
            CROSS JOIN LATERAL generate_series(1, 1 + floor(pg_temp.rnd(s.g, 20) * 3)::int) j
            WHERE pg_temp.rnd(s.g, 22) < 0.08
            ORDER BY 6
            """,
            {"labelers": LABELERS},
        )
        self.run(
            """
            UPDATE samples s SET review_count = r.n, accepted_count = r.acc, rejected_count = r.rej,
                   review_status = CASE WHEN r.n < 3 THEN 'in_review' WHEN r.acc = 3 THEN 'accepted'
                                        WHEN r.rej = 3 THEN 'rejected' ELSE 'conflict' END,
                   resolved_at = CASE WHEN r.n >= 3 THEN r.last END
            FROM (SELECT sample_id, count(*) AS n, count(*) FILTER (WHERE decision = 'accept') AS acc,
                         count(*) FILTER (WHERE decision = 'reject') AS rej, max(created_at) AS last
                  FROM sample_reviews GROUP BY sample_id) r
            WHERE s.id = r.sample_id
            """,
            what="sample review counts",
        )

    def sample_extras(self) -> None:
        """Channel geometry for every frame sample, two published detection
        models with recorded datasets, and two teacher jobs."""
        self.load(
            "sample_channel_geometry",
            """
            INSERT INTO sample_channel_geometry (id, sample_id, source_role, frame_width, frame_height,
                polygon_x, polygon_y, center_x, center_y, inner_radius, outer_radius, section_zero_angle_deg,
                reverse, created_at)
            SELECT md5('geometry:' || id)::uuid, id, source_role, 3840, 2160,
                   ARRAY(SELECT 1920 + 900 * cos(a * pi() / 12) FROM generate_series(0, 23) a),
                   ARRAY(SELECT 1080 + 900 * sin(a * pi() / 12) FROM generate_series(0, 23) a),
                   1920, 1080, 400, 900, 0, false, uploaded_at
            FROM samples WHERE full_frame_path IS NOT NULL
            """,
        )
        self.run(
            """
            INSERT INTO detection_models (id, owner_id, slug, version, name, description, model_family, scopes,
                training_metadata, is_public, published_at, updated_at, codename, experimental, purpose)
            SELECT md5('model:' || i)::uuid, md5('user:1')::uuid, 'chamber-detector', i, 'Detector v' || i, NULL,
                   'yolo', '["classification_channel"]'::jsonb, '{}'::jsonb, true,
                   now() - (60 - i * 20) * interval '1 day', now(), NULL, false, 'detection'
            FROM generate_series(1, 2) i
            """
        )
        # Model 1 trained on 40k older teacher-checked samples, model 2 on 80k.
        self.run(
            """
            INSERT INTO model_dataset_samples (model_id, sample_id, split)
            SELECT md5('model:' || m)::uuid, s.id, CASE WHEN pg_temp.rnd(s.g, 31) < 0.1 THEN 'val' ELSE 'train' END
            FROM (SELECT id, substr(local_sample_id, 2)::bigint AS g FROM samples
                  WHERE extra_metadata ? 'teacher_rerun' AND archived_at IS NULL) s,
                 generate_series(1, 2) m
            WHERE pg_temp.rnd(s.g, 30 + m) < m * %(share)s
            """,
            {"share": 40_000 / max(1, self.sizes.samples * 0.3 * 0.86 * 0.95)},
            what="model datasets",
        )
        self.run(
            """
            INSERT INTO teacher_jobs (id, owner_id, status, openrouter_model, filter_json, total, processed,
                succeeded, failed, created_at, started_at, finished_at, cost_usd, tokens_input, tokens_output)
            SELECT md5('teacher-job:' || j)::uuid, md5('user:1')::uuid, CASE WHEN j = 1 THEN 'done' ELSE 'running' END,
                   'google/gemini-2.5-flash', '{"annotated": "raw"}'::jsonb, 5000, 0, 0, 0,
                   now() - (10 - j * 4) * interval '1 day', now() - (10 - j * 4) * interval '1 day', NULL, 0, 0, 0
            FROM generate_series(1, 2) j;
            INSERT INTO teacher_job_items (id, job_id, sample_id, status, created_at, processed_at, detection_count)
            SELECT md5('teacher-item:' || j || ':' || id)::uuid, md5('teacher-job:' || j)::uuid, id,
                   CASE WHEN j = 1 OR n <= 3000 THEN 'done' ELSE 'queued' END,
                   now() - (10 - j * 4) * interval '1 day',
                   CASE WHEN j = 1 OR n <= 3000 THEN now() - (9 - j * 4) * interval '1 day' END, 2
            FROM (SELECT j, s.id, row_number() OVER (PARTITION BY j ORDER BY s.id) AS n
                  FROM generate_series(1, 2) j
                  CROSS JOIN LATERAL (SELECT id FROM samples WHERE source_role = 'classification_channel'
                                      ORDER BY id OFFSET j * 5000 LIMIT 5000) s) items;
            UPDATE teacher_jobs t SET processed = c.done, succeeded = c.done
            FROM (SELECT job_id, count(*) FILTER (WHERE status = 'done') AS done FROM teacher_job_items GROUP BY job_id) c
            WHERE t.id = c.job_id
            """,
            what="teacher jobs",
        )

    def pieces(self) -> None:
        n = self.sizes.pieces
        self.load(
            "machine_pieces",
            """
            INSERT INTO machine_pieces (id, machine_id, piece_uuid, local_id, run_id, seen_at, recorded_at,
                classification_status, part_id, part_name, color_id, color_name, category_id, confidence,
                bin_x, bin_y, bin_z, dead, brickognize_preview_url, created_at, brickognize_listing_id,
                brickognize_item_rank, brickognize_item_type, brickognize_color_rank, part_correct,
                color_corrected_id, part_feedback_submitted, color_feedback_submitted, correction_updated_at,
                color_provider, mold_provider, color_confidence)
            SELECT md5('piece:' || g)::uuid, m.id, md5('piece-uuid:' || g)::uuid::text, g,
                   'run-' || m.i || '-' || to_char(t.seen, 'YYYYMMDD'), t.seen, t.seen + interval '2 seconds',
                   c.status, CASE WHEN c.named THEN (3000 + c.part)::text END,
                   CASE WHEN c.named THEN 'Part ' || c.part END,
                   (ARRAY[11, 1, 5, 86, 85, 7, 2, 3, 88, 6, 4, 9, 10, 12, 13, 14, 15, 17, 18, 19,
                          20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 34, 36, 37, 38, 39, 40, 41, 42, 43, 44,
                          46, 47, 48, 49, 50, 51, 52, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66,
                          67, 68, 69, 70, 71, 72, 73, 74, 76, 77, 78, 80, 81, 82, 83, 84, 87, 89, 90, 91])
                   [1 + c.colour]::text,
                   'Colour ' || c.colour, (c.part %% 60)::text, round(pg_temp.rnd(g, 44)::numeric, 3),
                   CASE WHEN c.binned THEN 1 + (g %% 4) END, CASE WHEN c.binned THEN g %% 6 END,
                   CASE WHEN c.binned THEN g %% 12 END,
                   pg_temp.rnd(g, 45) < 0.10,
                   NULL, t.created, CASE WHEN pg_temp.rnd(g, 46) < 0.6 THEN left(md5('listing:' || g), 20) END,
                   0, 'P', 0, NULL, NULL, false, false, NULL,
                   CASE WHEN t.x > 0.4 THEN 'hive_color_model' ELSE 'brickognize' END, 'brickognize',
                   CASE WHEN t.x > 0.4 THEN round(pg_temp.rnd(g, 47)::numeric, 3) END
            FROM generate_series(1, %(n)s) g
            CROSS JOIN LATERAL (
                SELECT ((g - 0.5) / %(n)s)::float8 AS x,
                       now() - %(days)s * interval '1 day' * (1 - pg_temp.ramp(((g - 0.5) / %(n)s)::float8, 4))
                           + (pg_temp.rnd(g, 40) - 0.5) * interval '10 seconds' AS created
            ) t0
            CROSS JOIN LATERAL (
                -- Most pieces reach Hive within a minute of being seen; one in thirty comes
                -- up days later, from a machine that was offline.
                SELECT t0.x, t0.created,
                       t0.created - CASE WHEN pg_temp.rnd(g, 41) < 0.03 THEN (1 + pg_temp.rnd(g, 42) * 4) * interval '1 day'
                                         ELSE (5 + pg_temp.rnd(g, 42) * 50) * interval '1 second' END AS seen
            ) t
            CROSS JOIN LATERAL (
                SELECT i, md5('machine:' || i)::uuid AS id
                FROM width_bucket(pg_temp.rnd(g, 43), %(machine_cum)s::float8[]) i
            ) m
            CROSS JOIN LATERAL (
                SELECT (ARRAY['classified', 'unknown', 'not_found', 'multi_drop'])
                           [width_bucket(pg_temp.rnd(g, 48), ARRAY[0, 0.84, 0.92, 0.97])] AS status,
                       floor(3000 * power(pg_temp.rnd(g, 49), 3))::int AS part,
                       floor(80 * power(pg_temp.rnd(g, 50), 2))::int AS colour,
                       pg_temp.rnd(g, 51) < 0.9 AS binned,
                       pg_temp.rnd(g, 48) < 0.84 AS named
            ) c
            """,
            {"n": n, "days": self.sizes.days, "machine_cum": _cum(MACHINE_WEIGHTS)},
        )

    def piece_images(self) -> None:
        self.load(
            "machine_piece_images",
            """
            INSERT INTO machine_piece_images (id, machine_id, piece_uuid, seq, local_id, source, channel, ts,
                captured_at, sharpness, bytes, used, excluded_from_result, score, image_key, evicted_locally,
                created_at)
            SELECT md5('image:' || p.local_id || ':' || s)::uuid, p.machine_id, p.piece_uuid, s, p.local_id * 8 + s,
                   'classification', 4, p.seen_at - (5 - s) * interval '400 milliseconds',
                   p.seen_at - (5 - s) * interval '400 milliseconds', 50 + pg_temp.rnd(p.local_id * 8 + s, 60) * 400,
                   20000 + (pg_temp.rnd(p.local_id * 8 + s, 61) * 30000)::int, s = 0, false,
                   round(pg_temp.rnd(p.local_id * 8 + s, 62)::numeric, 3),
                   CASE WHEN pg_temp.rnd(p.local_id * 8 + s, 63) < 0.92
                        THEN 'machines/' || p.machine_id || '/pieces/' || p.piece_uuid || '/' || s || '.jpg' END,
                   false, p.created_at + s * interval '1 second'
            FROM machine_pieces p
            CROSS JOIN LATERAL generate_series(0, floor(pg_temp.rnd(p.local_id, 64) * 5)::int) s
            """,
        )

    def channel_crops(self) -> None:
        """Twelve per piece for the newest 81.5% of pieces (8% of those have
        none), timed in the minute before the piece reached C4: five on C2,
        then seven on C3, the last ones at the exit."""
        first = int(self.sizes.pieces * 0.185)
        self.load(
            "machine_channel_crops",
            """
            INSERT INTO machine_channel_crops (id, machine_id, local_id, channel, ts, captured_at, track_id,
                com_forward_to_exit_deg, com_section, zone_code, sharpness, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                bytes, image_key, evicted_locally, created_at)
            SELECT md5('crop:' || p.local_id || ':' || k)::uuid, p.machine_id, p.local_id * 16 + k,
                   CASE WHEN k < 5 THEN 2 ELSE 3 END, c.ts, c.ts, p.local_id * 2 + (k / 5),
                   (11 - k) * 9 + pg_temp.rnd(p.local_id * 16 + k, 70) * 5, k %% 6,
                   CASE WHEN k >= 10 THEN 2 WHEN k = 9 THEN 3 WHEN k >= 5 THEN 1 ELSE 0 END,
                   50 + pg_temp.rnd(p.local_id * 16 + k, 71) * 300,
                   (pg_temp.rnd(p.local_id * 16 + k, 72) * 1800)::int, (pg_temp.rnd(p.local_id * 16 + k, 73) * 1000)::int,
                   (pg_temp.rnd(p.local_id * 16 + k, 72) * 1800)::int + 120,
                   (pg_temp.rnd(p.local_id * 16 + k, 73) * 1000)::int + 120,
                   8000 + (pg_temp.rnd(p.local_id * 16 + k, 74) * 9000)::int,
                   CASE WHEN pg_temp.rnd(p.local_id * 16 + k, 75) < 0.95
                        THEN 'machines/' || p.machine_id || '/channel-crops/' || (p.local_id * 16 + k) || '.jpg' END,
                   false, p.created_at + k * interval '200 milliseconds'
            FROM machine_pieces p
            CROSS JOIN LATERAL generate_series(0, CASE WHEN pg_temp.rnd(p.local_id, 76) < 0.08 THEN -1 ELSE 11 END) k
            CROSS JOIN LATERAL (
                SELECT coalesce(p.seen_at, p.created_at)
                       - CASE WHEN k < 5 THEN (58 - k * 6 - pg_temp.rnd(p.local_id * 16 + k, 77) * 3)
                              ELSE (22 - (k - 5) * 3 - pg_temp.rnd(p.local_id * 16 + k, 77) * 1.5) END
                         * interval '1 second' AS ts
            ) c
            WHERE p.local_id > %(first)s
            """,
            {"first": first},
        )

    def piece_extras(self) -> None:
        """The machine's ranked predictions for the newest week's pieces, the
        operator's rejection reasons for 1%, and control-data segments."""
        self.load(
            "machine_piece_predictions",
            """
            INSERT INTO machine_piece_predictions (id, machine_id, piece_uuid, local_id, request, provider, model,
                kind, rank, value_id, value_name, score, applied, predicted_at, created_at)
            SELECT md5('prediction:' || p.local_id || ':' || k.kind || ':' || k.rank)::uuid, p.machine_id, p.piece_uuid,
                   p.local_id * 4 + k.rank, 'r1', 'brickognize', NULL, k.kind, k.rank,
                   coalesce(CASE WHEN k.kind = 'part' THEN p.part_id ELSE p.color_id END, '0') || '-' || k.rank,
                   NULL, 0.9 - k.rank * 0.2, k.rank = 0, p.seen_at, p.created_at
            FROM machine_pieces p
            CROSS JOIN (VALUES ('part', 0), ('part', 1), ('color', 0), ('color', 1)) k(kind, rank)
            WHERE p.created_at > now() - interval '7 days'
            """,
        )
        self.run(
            """
            INSERT INTO machine_piece_rejection_reasons (id, machine_id, piece_uuid, reason, created_at)
            SELECT md5('rejection:' || local_id)::uuid, machine_id, piece_uuid,
                   (ARRAY['no_piece', 'multiple_pieces', 'not_lego', 'blurry'])[1 + local_id %% 4], created_at
            FROM machine_pieces WHERE pg_temp.rnd(local_id, 80) < 0.01
            """,
            what="operator rejection reasons",
        )
        self.run(
            """
            INSERT INTO machine_control_data_segments (id, machine_id, local_id, started_at, ended_at, records,
                bytes, machine_setup, feeder_mode, classification_mode, autotune_mode, data_key, evicted_locally,
                created_at)
            SELECT md5('segment:' || m.i || ':' || h)::uuid, m.id, h, now() - h * interval '30 minutes',
                   now() - h * interval '30 minutes' + interval '29 minutes', 9000, 1500000, 'standard', 'auto',
                   'brickognize', 'off', 'machines/' || m.id || '/control/' || h || '.jsonl.gz', false,
                   now() - h * interval '30 minutes' + interval '30 minutes'
            FROM seed_machines m, generate_series(1, %(per_machine)s) h
            WHERE m.i <= 7 AND pg_temp.rnd(m.i * 100000 + h, 81) < 0.35
            """,
            {"per_machine": self.sizes.days * 48},
            what="control data segments",
        )

    def training_runs(self) -> None:
        """Ten colour runs of one segment on each of the three busiest machines:
        the newest still collecting (started 40 minutes ago), the rest an hour
        long, every three days; one in ten excluded, one in three of several
        colours. The
        pieces each saw are labelled as a sorter would label them (a run of
        one colour gives it; of several, the piece's own guess when it is one
        of them, nine times in ten), one in fifty excluded, and each run's
        counts are kept as a sync would leave them."""
        self.run(
            """
            INSERT INTO machine_training_runs (id, machine_id, run_uuid, mode, color_ids, segments, started_at,
                ended_at, excluded, updated_at, piece_count, labeled_count, excluded_count, created_at, received_at)
            SELECT md5('training-run:' || m.i || ':' || k)::uuid, m.id,
                   md5('training-run-uuid:' || m.i || ':' || k)::uuid::text, 'color', t.colors,
                   jsonb_build_array(jsonb_build_object(
                       'segment_uuid', md5('training-segment:' || m.i || ':' || k)::uuid::text,
                       'color_ids', t.colors, 'started_at', t.started, 'ended_at', t.ended)),
                   t.started, t.ended, k = 4, now(), 0, 0, 0, now(), now()
            FROM seed_machines m CROSS JOIN generate_series(0, 9) k
            CROSS JOIN LATERAL (
                SELECT s.started, CASE WHEN k > 0 THEN s.started + interval '1 hour' END AS ended,
                       CASE WHEN k %% 3 = 1 THEN '["5", "7", "3"]'::jsonb
                            ELSE jsonb_build_array((ARRAY['5', '11', '1', '86'])[1 + k %% 4]) END AS colors
                FROM (SELECT CASE WHEN k = 0 THEN now() - interval '40 minutes'
                                  ELSE now() - (k * 3) * interval '1 day' - m.i * interval '1 hour' END AS started) s
            ) t
            WHERE m.i <= 3
            """,
            what="training runs",
        )
        self.run(
            """
            UPDATE machine_pieces p
            SET training_run_uuid = r.run_uuid,
                training_segment_uuid = r.segments -> 0 ->> 'segment_uuid',
                training_color_id = CASE
                    WHEN jsonb_array_length(r.color_ids) = 1 THEN r.color_ids ->> 0
                    WHEN pg_temp.rnd(p.local_id, 140) < 0.9
                        THEN r.color_ids ->> (p.local_id %% jsonb_array_length(r.color_ids))::int END,
                training_label_source = CASE
                    WHEN jsonb_array_length(r.color_ids) = 1 THEN 'run'
                    WHEN pg_temp.rnd(p.local_id, 140) < 0.9 THEN 'prediction' END,
                training_excluded = pg_temp.rnd(p.local_id, 141) < 0.02,
                training_updated_at = coalesce(r.ended_at, now())
            FROM machine_training_runs r
            WHERE p.machine_id = r.machine_id AND p.seen_at >= r.started_at
              AND p.seen_at < coalesce(r.ended_at, now())
            """,
            what="training labels",
        )
        self.run(
            """
            UPDATE machine_training_runs r
            SET piece_count = c.n, labeled_count = c.labeled, excluded_count = c.excluded
            FROM (
                SELECT machine_id, training_run_uuid, count(*) AS n,
                       count(*) FILTER (WHERE training_color_id IS NOT NULL AND NOT training_excluded) AS labeled,
                       count(*) FILTER (WHERE training_excluded) AS excluded
                FROM machine_pieces WHERE training_run_uuid IS NOT NULL GROUP BY 1, 2
            ) c
            WHERE c.machine_id = r.machine_id AND c.training_run_uuid = r.run_uuid
            """,
            what="training run counts",
        )

    def labels(self) -> None:
        """Human work, written a piece at a time: about 4,000 colour labels on
        2,500 pieces, 1,000 same-piece crop links, 1,200 part labels, 300
        rejections and 2,500 image quality flags, from the 14 labelers, on the
        pieces the queue serves."""
        base = """
            FROM labeling_queue q JOIN machine_pieces p USING (machine_id, piece_uuid)
            CROSS JOIN LATERAL generate_series(1, 1 + floor(pg_temp.rnd(p.local_id, %(salt)s) * %(spread)s)::int) j
            WHERE pg_temp.rnd(p.local_id, %(salt)s + 1) < %(p)s
        """
        labeler = "md5('user:' || (1 + ((p.local_id * 3 + j * 5) %% 14)))::uuid"
        when = "least(now(), p.created_at + (1 + pg_temp.rnd(p.local_id * 4 + j, %(salt)s + 2) * 20) * interval '1 day')"
        self.run(
            f"""
            INSERT INTO piece_color_labels (id, machine_id, piece_uuid, labeler_id, color_id, notes, created_at,
                                            updated_at, cant_tell)
            SELECT md5('colour-label:' || p.local_id || ':' || j)::uuid, p.machine_id, p.piece_uuid, {labeler},
                   CASE WHEN pg_temp.rnd(p.local_id * 4 + j, 92) < 0.05 THEN NULL
                        WHEN pg_temp.rnd(p.local_id * 4 + j, 93) < 0.8 THEN p.color_id::int
                        ELSE (ARRAY[1, 5, 11, 86, 85, 7, 2, 3])[1 + (p.local_id + j) %% 8] END,
                   NULL, {when}, {when}, pg_temp.rnd(p.local_id * 4 + j, 92) < 0.05
            {base}
            """,
            {"salt": 90, "spread": 2.2, "p": 0.0025},
            what="colour labels",
        )
        self.run(
            f"""
            INSERT INTO piece_crop_links (id, machine_id, piece_uuid, labeler_id, arrival_ts, created_at, updated_at)
            SELECT md5('crop-link:' || p.local_id || ':' || j)::uuid, p.machine_id, p.piece_uuid, {labeler},
                   extract(epoch FROM p.seen_at), {when}, {when}
            {base} AND q.has_candidates;
            INSERT INTO piece_crop_link_members (id, link_id, crop_local_id, is_same, was_predicted, created_at)
            SELECT md5('crop-link-member:' || l.id || ':' || c.local_id)::uuid, l.id, c.local_id, c.channel = 3,
                   c.zone_code = 2, l.created_at
            FROM piece_crop_links l JOIN machine_pieces p USING (machine_id, piece_uuid)
            JOIN machine_channel_crops c ON c.machine_id = p.machine_id AND c.local_id BETWEEN p.local_id * 16 AND p.local_id * 16 + 7
            """,
            {"salt": 100, "spread": 1.6, "p": 0.0012},
            what="crop links",
        )
        self.run(
            f"""
            INSERT INTO piece_part_labels (id, machine_id, piece_uuid, labeler_id, part_num, cant_tell,
                                           predicted_part_num, notes, created_at, updated_at, part_correct)
            SELECT md5('part-label:' || p.local_id || ':' || j)::uuid, p.machine_id, p.piece_uuid, {labeler},
                   coalesce(p.part_id, '3001'), false, p.part_id, NULL, {when}, {when}, p.part_id IS NOT NULL
            {base}
            """,
            {"salt": 110, "spread": 1.4, "p": 0.0010},
            what="part labels",
        )
        self.run(
            f"""
            INSERT INTO piece_rejections (id, machine_id, piece_uuid, labeler_id, reasons, created_at, updated_at)
            SELECT md5('rejection-label:' || p.local_id || ':' || j)::uuid, p.machine_id, p.piece_uuid, {labeler},
                   '["blurry"]'::jsonb, {when}, {when}
            {base}
            """,
            {"salt": 120, "spread": 1.0, "p": 0.0003},
            what="rejections",
        )
        self.run(
            f"""
            INSERT INTO image_quality_labels (id, machine_id, labeler_id, crop_kind, piece_uuid, seq, crop_local_id,
                high_quality, low_resolution, motion_blur, not_contained, no_piece_in_frame, other_bad, created_at,
                updated_at)
            SELECT md5('quality:' || p.local_id || ':' || j)::uuid, p.machine_id, {labeler}, 'piece_image',
                   p.piece_uuid, 0, NULL, j = 1, false, j = 2, false, false, false, {when}, {when}
            {base}
            """,
            {"salt": 130, "spread": 1.5, "p": 0.0017},
            what="image quality flags",
        )

    def swatches(self) -> None:
        """The active swatch model has read the classification channel frames
        of the last day and 0.5% of the older ones; the previous model a few
        hundred. A backfill of the rest is queued as jobs."""
        self.run(
            """
            INSERT INTO swatch_models (id, filename, name, description, kind, sha256, colour_count, net_long_side,
                                       file_size, meta, is_active, created_at, updated_at)
            VALUES (md5('swatch-model:1')::uuid, 'swatch-v1.onnx', 'swatch v1', NULL, 'swatch_finder', %(old)s, 12,
                    960, 20000000, '{}'::jsonb, false, now() - interval '20 days', now() - interval '5 days'),
                   (md5('swatch-model:2')::uuid, 'swatch-v2.onnx', 'swatch v2', NULL, 'swatch_finder', %(active)s, 12,
                    960, 20000000, '{}'::jsonb, true, now() - interval '5 days', now() - interval '5 days')
            """,
            {"old": SWATCH_MODEL_OLD, "active": SWATCH_MODEL_ACTIVE},
        )
        self.load(
            "sample_swatch_runs",
            """
            INSERT INTO sample_swatch_runs (id, sample_id, model_id, model_name, model_sha256, frame_width,
                frame_height, swatch_count, flags, seconds, created_at, palette_present, palette_swatches,
                machine_id, frame_at)
            SELECT md5('swatch-run:' || s.id || ':' || v.n)::uuid, s.id, md5('swatch-model:' || v.n)::uuid,
                   'swatch v' || v.n, v.sha, 3840, 2160, 10 + (s.g %% 12), '[]'::jsonb, 1.5,
                   least(now(), s.uploaded_at + interval '10 minutes'),
                   CASE WHEN pg_temp.rnd(s.g, 140 + v.n) < 0.05 THEN NULL ELSE pg_temp.rnd(s.g, 142 + v.n) < 0.58 END,
                   8 + (s.g %% 6), s.machine_id, coalesce(s.captured_at, s.uploaded_at)
            FROM (SELECT id, machine_id, captured_at, uploaded_at, substr(local_sample_id, 2)::bigint AS g FROM samples
                  WHERE source_role = ANY(%(roles)s) AND full_frame_path IS NOT NULL) s
            CROSS JOIN (VALUES (2, %(active)s), (1, %(old)s)) v(n, sha)
            WHERE (v.n = 2 AND (s.uploaded_at > now() - interval '1 day' OR pg_temp.rnd(s.g, 143) < 0.005))
               OR (v.n = 1 AND pg_temp.rnd(s.g, 144) < 0.002)
            ORDER BY s.uploaded_at
            """,
            {"roles": list(settings.SWATCH_FIND_SOURCE_ROLES), "active": SWATCH_MODEL_ACTIVE, "old": SWATCH_MODEL_OLD},
        )
        self.load(
            "sample_swatches",
            """
            INSERT INTO sample_swatches (id, run_id, position, colour, bricklink_color_id, colour_score,
                surface_score, pixels, median_r, median_g, median_b, std_r, std_g, std_b, clipped, centre_x, centre_y,
                box_x0, box_y0, box_x1, box_y1, length, width, flags, in_palette)
            SELECT md5('swatch:' || r.id || ':' || k)::uuid, r.id, k, 'colour-' || (k %% 12), 1 + k %% 12, 0.9, 0.95,
                   900, 100 + k, 120, 140, 3, 3, 3, 0.0, 100 + k * 40, 300, 80 + k * 40, 280, 120 + k * 40, 320,
                   40, 40, '[]'::jsonb, r.palette_present
            FROM sample_swatch_runs r CROSS JOIN LATERAL generate_series(0, r.swatch_count - 1) k
            """,
        )
        self.run(
            """
            INSERT INTO jobs (id, kind, subject, payload, status, priority, attempts, max_attempts, run_after,
                              locked_by, locked_until, error, result, created_at, started_at, finished_at, updated_at)
            SELECT md5('job:' || r.sample_id)::uuid, 'swatch_find', r.sample_id::text, NULL, 'done', 0, 1, 3,
                   r.created_at, NULL, NULL, NULL, '{"swatches": 12}'::jsonb, r.created_at, r.created_at,
                   r.created_at + interval '2 seconds', r.created_at + interval '2 seconds'
            FROM sample_swatch_runs r WHERE r.model_sha256 = %(active)s AND r.created_at > now() - interval '2 days';
            INSERT INTO jobs (id, kind, subject, payload, status, priority, attempts, max_attempts, run_after,
                              locked_by, locked_until, error, result, created_at, started_at, finished_at, updated_at)
            SELECT md5('job:' || s.id)::uuid, 'swatch_find', s.id::text, NULL,
                   CASE WHEN pg_temp.rnd(s.g, 150) < 0.006 THEN 'failed' ELSE 'queued' END, -1,
                   0, 3, now() - interval '1 hour', NULL, NULL, NULL, NULL, now() - interval '1 hour', NULL,
                   CASE WHEN pg_temp.rnd(s.g, 150) < 0.006 THEN now() - interval '30 minutes' END, now()
            FROM (SELECT id, substr(local_sample_id, 2)::bigint AS g FROM samples
                  WHERE source_role = ANY(%(roles)s) AND full_frame_path IS NOT NULL
                    AND uploaded_at <= now() - interval '1 day') s
            WHERE NOT EXISTS (SELECT 1 FROM sample_swatch_runs r WHERE r.sample_id = s.id)
              AND pg_temp.rnd(s.g, 151) < 0.12
            """,
            {"roles": list(settings.SWATCH_FIND_SOURCE_ROLES), "active": SWATCH_MODEL_ACTIVE},
            what="swatch jobs",
        )

    def worker_passes(self) -> None:
        """What a running Hive's workers keep: the labeling queue and its
        counts, and the per-machine and per-day stats."""
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from app.services import labeling_queue, machine_stats

        engine = create_engine(settings.DATABASE_URL, connect_args={"options": "-c statement_timeout=0"})
        session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            started = time.monotonic()
            result = labeling_queue.run_pass(session)
            session.commit()
            log.info("labeling queue: %s (%.0f s)", result, time.monotonic() - started)
            started = time.monotonic()
            session.execute(text("SET work_mem = '256MB'"))
            machine_stats.refresh_all(session)
            log.info("machine stats (%.0f s)", time.monotonic() - started)
        finally:
            session.close()
            engine.dispose()

    def vacuum(self) -> None:
        self.conn.autocommit = True
        started = time.monotonic()
        self.cur.execute("VACUUM (ANALYZE)")
        log.info("VACUUM ANALYZE (%.0f s)", time.monotonic() - started)
        self.conn.autocommit = False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", type=float, default=1.0, help="1.0 is production's size (default)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    sizes = Sizes.at(args.scale)
    conn = psycopg2.connect(settings.DATABASE_URL)
    seeder = Seeder(conn, sizes)
    seeder.refuse_unless_empty()
    seeder.run(SESSION_SETUP)
    log.info("seeding %s", sizes)
    seeder.people_and_machines()
    seeder.samples()
    seeder.reviews()
    seeder.sample_extras()
    seeder.pieces()
    seeder.piece_images()
    seeder.channel_crops()
    seeder.piece_extras()
    seeder.training_runs()
    seeder.swatches()
    seeder.worker_passes()
    seeder.labels()
    seeder.vacuum()
    conn.close()
    log.info("done")


if __name__ == "__main__":
    main()

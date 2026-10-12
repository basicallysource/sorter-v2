# No request scans history: the query-plan test

Every list and count the API serves reads a bounded number of rows, however
long the fleet's history gets: a keyset walk of an index that leads with the
list's filter, a table a worker keeps, or a number a worker maintains. A
request never aggregates, sorts or counts what machines have written over
time. `backend/tests/test_query_plans.py` enforces it on a production-sized
database built by `backend/scripts/seed_large.py`.

## Running it

1. A throwaway Postgres 16 started with production's settings (the `command:`
   of `docker-compose.prod.yml`: `shared_buffers=1GB`, `work_mem=16MB`,
   `random_page_cost=1.1`, `jit=off`, ...). Plans depend on them.
2. Build the database (about 25 minutes and 8 GB at scale 1; `--scale 0.02`
   for a quick one). It refuses a database that already has users, machines
   or samples.

   ```
   cd software/hive/backend
   export DATABASE_URL=postgresql://USER@HOST:PORT/DB
   uv run alembic upgrade heads
   uv run python -m scripts.seed_large
   ```

3. Run the test against it. Nothing it does is committed: each request runs in
   a transaction that is rolled back.

   ```
   HIVE_QUERY_PLAN_DB_URL=$DATABASE_URL uv run pytest tests/test_query_plans.py
   ```

   `HIVE_QUERY_PLAN_REPORT=report.jsonl` also writes every case's time, rows
   read and plan shape, one JSON line per case.

A database seeded before a migration can be brought forward with
`alembic upgrade heads` and one pass of the stats worker
(`machine_stats.refresh_all`), which fills the tables it keeps.

## What it checks

Each `Case` is a request a page makes, with the filters a person can pick.
The test sends it through the app, catches every SELECT the code runs, runs it
under `EXPLAIN (ANALYZE, BUFFERS)` in the request's own transaction, and fails
when a plan

- reads a history table with a sequential scan;
- reads more rows of history than the case's budget (`BUDGET`, 3,000: rows a
  scan returned plus rows its filter threw away, over every scan of history in
  the statement); or
- sorts, hashes or aggregates more than `MAX_SORTED` (5,000) rows of history.

History (`HISTORY`) is what machines write: samples, pieces, crops, the
labeling queue and their kin. What people write (reviews, labels) grows at the
speed of people, and `jobs` holds work in flight, so neither counts.

A case that legitimately reads more says so in `why`, with its own budget: a
reviewer's window of the newest pieces, a bulk action's preview counted up to
the action's cap, the last day of pieces for the public live counters, one
teacher job's items, the records API's newest 20,000 pieces, and similar
samples, which compare a hash with every sample's (no index can narrow a
Hamming distance) through a narrow index rather than the table.

## When a case fails

The failure prints each offending statement, the rule it broke and its plan
shape (the scans of history with rows read, and the sorts and aggregates with
the rows they took in). The fix is one of:

- **An index the walk can follow**, leading with the filter and ending with the
  sort, built `CONCURRENTLY` in its migration (inside
  `op.get_context().autocommit_block()`), its predicate written exactly as the
  query writes it so the planner matches it, and declared on the model.
- **A bounded walk**: the samples list looks at `SAMPLE_WINDOW` rows of its
  index per request (`review_queue.sample_page`), the crop list
  `CROP_WINDOW`; a page can come back short with a cursor and the client asks
  again (`reviewQueue.svelte.ts`).
- **A number or table a worker keeps**: `machine_stats_cache` (counts per
  machine, including channel crops and the control-data summary),
  `machine_daily_stats`, `labeling_queue` and `labeling_queue_counts`,
  `sample_diversity_weekly`, `model_dataset_machines`.

## Adding an endpoint

Add a `Case` for each view of it a person can pick (filters, sorts, roles,
the second page), run the test, and fix what it finds before shipping. When
the seed lacks the data a new endpoint reads, add it to `seed_large.py`, in
production's shape.

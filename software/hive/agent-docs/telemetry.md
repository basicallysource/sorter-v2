# Machine telemetry

How each sorter is set up and how it runs, kept so the fleet's normal
behaviour can be known: how much load a chute normally sees at its speed,
what a camera's auto exposure settles on, how often steppers stall and under
which settings. It is not shown to a machine's owner; nothing in the UI reads
it yet. The uses come later; the records are kept small and regular so they
can be queried across the whole fleet when they do.

## Where it comes from

A sorter writes telemetry records locally (`software/sorter/backend/fleet_telemetry.py`,
stored by `telemetry_store.py`) and its sync worker sends them on the
`machine_telemetry` sharing stream, which is required: a sorter connected to a
Hive always sends it (`sharing.py` on the sorter; the person agrees to it when
they connect).

`POST /api/machine/sync/telemetry` (machine token, JSON batch `{"records": [...]}`)
upserts each record into `machine_telemetry` by `(machine_id, local_id)`: records
never change on the machine, so they sync by their local id like crops do, and
the data type `telemetry` keeps the watermark (`GET /api/machine/sync/state`).
A bad record (an unknown form, a kind that is not `snake_case`, `ended_at`
before `started_at`, data over 64 KB) is skipped and the watermark moves past
it, as in every batch endpoint.

## A record

| Column | What |
|---|---|
| `kind` | What it describes (below). |
| `form` | `snapshot`: state, written only when it changed. `window`: a distribution over a stretch of sorting, at most an hour, closed when sorting stops. `event`: something rare, with its context. |
| `schema` | The version of `data`'s shape for its kind. Raised when a field changes meaning; readers branch on it. |
| `started_at`, `ended_at` | The stretch a window covers; equal for a snapshot or an event. |
| `data` | JSONB, the kind's document. |

## Kinds

**`machine_specs`** (snapshot, at each start and whenever it changes): the
specs snapshot (`software/sorter/backend/machine_specs.py`, `schema_version`
3): platform, OS, software version, cameras with their saved settings,
controller boards, and each stepper's driver settings (`steppers`:
`irun`, `ihold`, `microsteps`, `stealthchop`, `coolstep`, `stallguard`,
`sgthrs`, `tcoolthrs`, `inverted`, and which of them `saved` in machine.toml
rather than built-in defaults). The newest one in a batch also becomes the
machine's dashboard summary and its hardware history
(`app/machine_hardware.py`), which is what specs on a heartbeat did; sorters
still send specs on the heartbeat to a Hive that 404s this endpoint.

**`stepper_load`** (window): per stepper, read while sorting, round robin
among the steppers that just moved (`TICK_S` 0.25 s, so each moving stepper a
few times a second):

```json
{"sample_interval_s": 0.25, "sg_bin_width": 32, "sorting_s": 3412.5,
 "steppers": {"chute": {
   "samples": 812, "standstill": 401, "stalls": 0,
   "settings": {"irun": 16, "ihold": 4, "microsteps": 8, "stealthchop": true, "coolstep": false,
                "stallguard": true, "sgthrs": 55, "tcoolthrs": 150},
   "flags": {"ola": 3},
   "bands": [{"tstep": [108, 128], "n": 230, "sg": [0, 0, 1, 3, 9, 30, 61, 70, 40, 12, 3, 1, 0, 0, 0, 0],
              "sg_min": 75, "sg_max": 376, "sg_sum": 52510, "cs_min": 16, "cs_max": 16, "cs_sum": 3680}]}}}
```

- `samples` counts DRV_STATUS reads; `standstill` those with the motor at rest
  (no SG_RESULT or TSTEP is read then).
- `bands` are quarter-octave bands of TSTEP, the driver's measured time
  between microsteps (`tstep: [lo, hi)`); speed is inversely proportional to
  it, so a stepper's cruise speed is its fullest band and the sparse bands
  around it are acceleration. Each band's `sg` is a histogram of SG_RESULT in
  `sg_bin_width` steps (0-31, 32-63, ...); SG_RESULT is StallGuard's load
  figure, lower meaning more load, and only meaningful in StealthChop at a
  settled speed. CS_ACTUAL (the current scale the driver used) is given as
  min, max and sum.
- `flags` counts readings with each DRV_STATUS flag set (`otpw`, `ot`, `s2ga`,
  `s2gb`, `s2vsa`, `s2vsb`, `ola`, `olb`, `t120`, `t143`, `t150`, `t157`);
  absent flags were never set.
- A change of any stepper's settings closes the window, so one window's
  readings are under one set of settings.

**`stepper_stall`** (event): a stall the firmware latched (`stepper`), the
stepper's `settings`, `sorting` (whether the machine was sorting), and `recent`:
its last readings before the stall, `[seconds before, sg, tstep, cs, standstill]`.

**`camera_readings`** (window): per camera role, every 5 minutes while sorting:
`model`, `n` readings, `fps` (measured from frames captured: min, max, mean,
last) and `controls`: each UVC control as the driver reports it (exposure,
gain, white balance temperature, auto exposure mode, brightness, ...), with
`min`, `max`, `mean` and `last`. With auto exposure or white balance on these
are the values the camera chose.

## Size

A sorting hour writes about 3 KB per machine (one stepper window, one camera
window); snapshots and stalls are rare. A thousand machines sorting six hours a
day add about 20 MB a day.

## Reading it

Nothing in the API serves it yet; query it directly. Examples:

```sql
-- One machine's stepper windows, newest first.
SELECT started_at, ended_at, data->'steppers'->'chute' FROM machine_telemetry
WHERE machine_id = :id AND kind = 'stepper_load' ORDER BY started_at DESC LIMIT 20;

-- Across the fleet: each chute window's fullest band (its cruise speed) and
-- that band's mean SG_RESULT, with the threshold it ran under.
SELECT t.machine_id, t.started_at, b->'tstep' AS tstep, (b->>'n')::int AS n,
       (b->>'sg_sum')::float / NULLIF((b->>'n')::int, 0) AS sg_mean,
       t.data->'steppers'->'chute'->'settings'->>'sgthrs' AS sgthrs
FROM machine_telemetry t,
     LATERAL (SELECT b FROM jsonb_array_elements(t.data->'steppers'->'chute'->'bands') b
              ORDER BY (b->>'n')::int DESC LIMIT 1) top
WHERE t.kind = 'stepper_load' AND t.started_at > now() - interval '30 days';
```

`ix_machine_telemetry_machine_kind_started` serves one machine's records of a
kind, `ix_machine_telemetry_kind_started` the fleet's. An endpoint that serves
these to a page follows [query-plans.md](query-plans.md).

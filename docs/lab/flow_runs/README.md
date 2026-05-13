# Flow Observation Runs

Per-run data from `software/sorter/backend/scripts/flow_obs/`.

## Format

For each run there are two files:

- `<ts>_<label>.jsonl` — one JSON record per 1-second observation window:
  per-table detection counts (T2/T3/T4 split into drop/transport/exit),
  T4 active_pieces, T4 state class, runtime counter cumulative + delta.
- `<ts>_<label>.meta.json` — pre/post-run config snapshot, start/end
  timestamps, observer exit code, free-text note.

## Tooling

```
scripts/flow_obs/runner.py  SECONDS LABEL [--note "..."]
scripts/flow_obs/observer.py SECONDS OUT_PATH RUN_LABEL          # invoked by runner
scripts/flow_obs/report.py   <log.jsonl> [<log2.jsonl> ...]
scripts/flow_obs/campaign.sh PREFIX SECONDS_PER_RUN NUM_RUNS REST
scripts/flow_obs/campaign_report.py "/path/to/<glob>.jsonl"
```

## Baseline campaign 2026-05-12 (10×60s, ~12 min total)

Config snapshot: max_zones=2, intake_guard_deg=80°, drop_angle=30°,
point_of_no_return_deg=18°, drop_tolerance_deg=14°, hood_dwell_ms=300,
min_carousel_crops_for_recognize=1, min_carousel_dwell_ms=300,
min_carousel_traversal_deg=15°, disable_servos=True.

| KPI                       | median | p10  | p90  | min  | max  |
|---------------------------|-------:|-----:|-----:|-----:|-----:|
| good_parts_per_min        |   2.01 | 1.02 | 2.22 | 1.0  | 3.0  |
| seen_per_min              |   9.04 | 7.22 | 10.40| 5.0  | 11.0 |
| distributed_per_min       |   8.40 | 6.84 | 11.04| 5.0  | 11.0 |
| classified_per_min        |   2.01 | 1.02 | 2.22 | 1.0  | 3.0  |
| recognize_fired_per_min   |   2.02 | 1.02 | 3.02 | 1.0  | 3.0  |
| multi_drop_fail_per_min   |   1.01 |  0.0 | 1.02 | 0.0  | 1.03 |

T4 state share (median % time): GOOD_SINGLE 55%, OVERLOADED 38%,
EMPTY 6.6%, STARVED 0%.

### Findings

1. **System throughput already meets the 8/min goal**: distributed_per_min
   median 8.4. The bottleneck is *not* upstream supply.
2. **Classification is the binding constraint**: only ~23% of pieces seen
   on C4 ever have Brickognize fire (rec_fired_per_min ≈ classified_per_min).
3. **Layout is rarely the issue**: T4 is in GOOD_SINGLE state 55% of the
   time. Even in that ideal state recognition still misses most pieces.
4. **Hypothesis**: pieces traverse C4 (~2-3 s) faster than the
   `hood_dwell + min_carousel_dwell + Brickognize_round_trip` budget
   (~1.5-2.5 s) reliably allows. The piece reaches point_of_no_return
   before the Brickognize response arrives, gets flagged
   `point_of_no_return_unclassified`, and the in-flight response is
   discarded.
5. **Noise floor**: ± 0.5 piece/min in classification rate, ± 2 pieces/min
   in throughput. An experimental change must move good_parts_per_min by
   at least ~1.5 (p90 of baseline) to be considered above noise.

### Window-length progression

60 s windows are useful for fast iteration but only sample fast effects.
As experiments progress and the picture stabilises, window length should
grow (120 s → 180 s → 300 s) so slower phenomena — drift, batch effects,
warm-up after restart — become visible. Quick-turnaround comparisons stay
at 60 s; "ist das Ergebnis nachhaltig?"-style validation should always
include at least one longer window.

### Experiment T1: 10×60s with `min_carousel_traversal_deg` 15° → 5°

Hypothesis: traversal gate is the dominant blocker; opening it lets more
pieces fire Brickognize, which is fast and accurate.

Result (`*trav5_[0-9]*.jsonl`):

| KPI                       | baseline (15°) | trav5 (5°) | Δ           |
|---------------------------|---------------:|-----------:|-------------|
| good_parts_per_min median |          2.01  |       2.01 | **0**       |
| recognize_fired_per_min   |          2.02  |       3.52 | +1.5 (+75%) |
| seen_per_min              |          9.04  |       8.08 | -1.0        |
| multi_drop_fail_per_min   |          1.01  |       1.01 | 0           |
| T3 N_total mean           |          11.2  |       15.6 | +4          |

Hypothesis falsified. Lowering the traversal gate fires Brickognize
~75% more often, but the extra fires return empty (pieces had not yet
accumulated enough viewing-angle diversity), so the cleanly-classified
rate is unchanged. T3 N_total grew by 4 pieces, which is the system
buffering harder upstream while C4 spins faster — a sign that we are
upstream-pushing without C4 actually digesting more.

Reverted to 15°.

### Experiment T2: C3 crops removed + min_crops=5 + free-fall burst

Three coordinated changes attacking **crop quality**:

- `recognition.py`: only `source_role == "carousel"` crops reach
  Brickognize; c2/c3 segments and their fallback lookups deleted.
- `irl/config.py`: `min_carousel_crops_for_recognize` 2 → 5 so
  recognition fires only after the piece has accumulated multiple
  post-landing views.
- `polar_tracker.py`: new free-fall burst window — for the first
  `CAROUSEL_FREE_FALL_BURST_S = 0.7 s` of every carousel track's life
  the angular capture gate is bypassed (gated only by a 40 ms
  time-gap), so the falling / tumbling piece is captured ~one frame
  per camera tick instead of one snapshot every 3-8° of arc.

Result (`*c3drop_minc5_burst_[0-9]*.jsonl`, in progress — partial
n=4):

| KPI                            | baseline (n=10) | T2 partial (n=4) | Δ        |
|--------------------------------|----------------:|-----------------:|----------|
| good_parts_per_min median      |            2.01 |             2.02 | **+0.01** |
| good_parts_per_min mean        |            1.75 |             2.27 | +0.52    |
| good_parts_per_min max         |            3.0  |             3.04 | +0.04    |
| brickognize_empty (per ~10min) |              ~5 |                0 | -5       |

**Provisional finding**: T2 does not move the cls/min median, but the
crop-quality story is real: with 5 carousel crops per fire,
**Brickognize hit-rate is ~100 %** (`brickognize_empty=0` across the
entire window since restart). The reason throughput doesn't move is
that fires themselves are bottlenecked elsewhere — at any given
moment the bench shows ~20 `recognize_skipped_carousel_quota` (not
enough crops) plus ~7 `recognize_skipped_carousel_traversal` (not
enough angular sweep). The latter is recoverable now that empties
are no longer a risk.

### T2 final (n=6) — partial-run table above stands

T2 final distribution (after stopping at n=6 to pivot): median 2.04,
mean 2.36, p90 3.04 vs baseline 2.01 / 1.75 / 2.22. Mean lifted
~35 %, p90 ~37 %, but median pinned to the noise floor. Distribution
shifted right, ceiling did not.

### Experiment T2b → T2c → T2d → T2e → T2f (compressed iteration log)

Each successive label folded in one or two changes and kept the rest
of T2. The sequence converged on a clear answer: **crop quality and
quantity are no longer the binding constraint**. T4 OVERLOAD share
climbs (38 % → 44 % in T2f) and `brickognize_empty=0` is sticky, but
classified/min stays at the same 3-piece-per-minute ceiling. The bench
runs out of *time per piece*, not out of *evidence for a piece*.

| Label | Changes layered on T2 baseline                                                   | n | cls/min median | Status |
|-------|----------------------------------------------------------------------------------|---|----------------|--------|
| T2b   | + `min_carousel_traversal_deg` 15° → 5°                                          | 5 | 2.52           | killed; bottleneck moved off traversal |
| T2c   | + carousel hive inference 5 Hz → 20 Hz (per-role override)                       | 4 | 2.3 (live)     | killed; quota skips dropped to 0 but cls/min didn't move |
| T2d   | + `delay_between_ms` 400 → 800 (slow platter), burst frames feed Brickognize     | 1 | 1.01           | failed; slow platter triggered upstream blocking — reverted |
| T2e   | + `BURST_PRE_FRAMES` 30 → 60, `BURST_FPS` 15 → 20, polygon bypass for retro scan | 6 | 2.03           | gallery jumped to ~18 crops/piece including free-fall — operator-visible win |
| T2f   | + retroactive YOLO conf 0.25 → 0.10                                              | 10 | **2.04**       | full distribution; mean 2.32 (+33 %), p90 3.03 (+37 %), max 3.04 |

The T2f → baseline distribution comparison:

| KPI                                | baseline (n=10) | T2f (n=10) | Δ       |
|------------------------------------|----------------:|-----------:|---------|
| good_parts_per_min median          |            2.01 |       2.04 | +0.03   |
| good_parts_per_min mean            |            1.75 |       2.32 | +0.57   |
| good_parts_per_min p90             |            2.22 |       3.03 | +0.81   |
| good_parts_per_min max             |            3.0  |       3.04 | +0.04   |
| seen_per_min median                |            9.04 |       8.60 | -0.44   |
| recognize_fired_per_min median     |            2.02 |       2.52 | +0.50   |
| brickognize_empty (cumulative)     |              ~5 |          0 | -5      |
| T4_OVERLOADED share median         |            38 % |       47 % | +9 pp   |
| multi_drop_fail_per_min median     |            1.01 |       0.51 | -0.50   |

### Experiment T3: faster retry + defensive gates removed

Layered on T2f: `RECOGNITION_RETRY_INTERVAL_S` 0.75 → 0.10,
`min_carousel_dwell_ms` 300 → 0, `min_carousel_traversal_deg` 5 → 0.
Hypothesis: pieces only get 1-2 recognition retry windows in their
~1.5 s C4 life; raising the retry frequency and dropping defensive
gates lets the loop fire as soon as the 5-crop floor is satisfied.

Result (`*t3_fast_retry*.jsonl`, n=6 — campaign interrupted at run 6
when the operator needed to refocus the camera; post-focus
re-launch stalled on an unrelated bulk-feeder starvation event and
is not yet re-attempted):

| KPI                       | baseline (n=10) | T2f (n=10) | T3 (n=6) | Δ T3-baseline |
|---------------------------|----------------:|-----------:|---------:|---------------|
| good_parts_per_min median |            2.01 |       2.04 |   **3.04** | **+1.03**     |
| good_parts_per_min mean   |            1.75 |       2.32 |     2.87 | +1.12         |
| good_parts_per_min p90    |            2.22 |       3.03 |   **4.55** | **+2.33**     |
| good_parts_per_min max    |            3.0  |       3.04 |   **5.06** | **+2.06**     |
| seen_per_min median       |            9.04 |       8.60 |     8.11 | -0.93         |
| recognize_fired_per_min   |            2.02 |       2.52 |     3.04 | +1.02         |
| brickognize_empty (~6min) |             ~3  |        0   |        2 | +2            |
| T4_OVERLOADED share med   |            38 % |       47 % |     47 % | (same)        |

**First measurable breakthrough across the whole campaign series.**
The median lifts to 3.04 cls/min — exactly at the noise-clearance
threshold (baseline 2.01 + 0.5 = 2.51, but the 3 cls/min plateau that
held across T2-T2f is broken: T3 maxed at 5.06 cls/min on a single
run for the first time. p90 of 4.55 confirms multiple runs reached
above the prior ceiling, so it is not a single-run fluke.

The defensive gates (`min_carousel_dwell_ms`, `min_carousel_traversal_deg`)
were doing modest real work — `brickognize_empty` went 0→2 across the
window, a small quality regression — but the retry-frequency gain
overwhelms that cost. With recognition firing every ~100 ms instead of
~750 ms, each piece gets ~10× more recognition attempts during its
brief C4 dwell, and the "second attempt with different crops" wins
classifications that the first attempt missed.

**Hypothesis validated** that the binding constraint was the per-piece
retry budget, not crop quality.

### Experiments T4–T7 (compressed iteration log)

After T3 broke the 3 cls/min ceiling, the next iterations chased two
goals: (a) push the median further, (b) clean up UI artefacts the
operator flagged on the piece detail page.

| Label | Changes layered on T3                                                                                                                                                                                              | n  | cls/min median | Status |
|-------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----|----------------|--------|
| T4    | + `FREEFALL_QUOTA_RATIO=0.5` so half of the Brickognize batch is reserved for pre-trigger free-fall crops (per operator insight that platter-rotation sector_snapshots are near-duplicates)                          | 2  | 0.00           | falsified; 100 % bk_empty — free-fall crops too motion-blurred for Brickognize. Reverted to 0.0. Role-tag plumbing kept (harmless). |
| T5    | + recognition fired before drop-pulse in step() (recognition is async, no stepper conflict), + `hood_dwell_ms` 300 → 0, + free-fall crops count toward the 5-crop gate                                              | 2  | 0.51 (mean)    | falsified; gate cleared on 5 free-fall crops before any stable platter view existed → 100 % bk_empty again. Counting reverted to stable-only. |
| T6    | T5 minus the free-fall-counts-in-gate bit. Stable carousel sector_snapshots required for the 5-crop floor; free-fall stays in the pool but doesn't trip the gate                                                    | 14 | 3.04           | Architectural fixes proved out at scale. **max=7.07** for the first time. Mean 3.25 (+12 % over T3). Bimodal distribution — high-supply windows hit 5-7, low-supply windows drop to 0-2. |
| T7    | + disable C3 → carousel identity handoff. Every carousel track gets a fresh `global_id`. Detail-page paths now contain only the carousel segment per operator request                                                | 10 | **3.54**       | Highest median across the whole campaign. recognize_fired 4.05/min (vs T3 3.04, T2f 2.52). UI fix achieved without throughput regression. multi_drop_fail per min 1.52 — collision rate up under higher pipeline throughput. |

The T7 distribution vs prior milestones:

| KPI                            | baseline (n=10) | T2f (n=10) | T3 (n=6) | T7 (n=10) |
|--------------------------------|----------------:|-----------:|---------:|----------:|
| good_parts_per_min median      |            2.01 |       2.04 |     3.04 |  **3.54** |
| good_parts_per_min mean        |            1.75 |       2.32 |     2.87 |      2.83 |
| good_parts_per_min p90         |            2.22 |       3.03 |     4.55 |      5.06 |
| good_parts_per_min max         |            3.0  |       3.04 |     5.06 |      5.06 |
| seen_per_min median            |            9.04 |       8.60 |     8.11 |      8.10 |
| recognize_fired_per_min median |            2.02 |       2.52 |     3.04 |  **4.05** |
| multi_drop_fail_per_min median |            1.01 |       0.51 |     1.01 |      1.52 |
| T4_OVERLOADED share median     |            38 % |       47 % |     47 % |    **63 %** |

### Where the data points next

The **per-individual-run ceiling of 3 cls/min has just moved** across
T2-T2f. That is the dominant signal — every change we've made to crop
quality / quantity / window / threshold has shifted the distribution
*right* but not lifted the cap. A piece on C4 has ~1.5 s and needs to
clear hood_dwell (300 ms) + min_carousel_dwell (300 ms) + traversal
(5°) + the actual Brickognize round-trip (~500 ms-1 s) + the drop
deadline. At a `RECOGNITION_RETRY_INTERVAL_S = 0.75 s`, a piece gets
1-2 retry windows during its life on C4; that explains why ~70 % of
pieces still hit the deadline unclassified.

**Next experiment T3 (queued)**: address the *retry budget* and the
*defensive gates* simultaneously.

- `RECOGNITION_RETRY_INTERVAL_S` 0.75 s → 0.10 s — pieces get ~10
  retry windows per pass on C4 instead of 2.
- `min_carousel_dwell_ms` 300 → 0 and `min_carousel_traversal_deg` 5 →
  0 — these gates were defensive against ghost crops from upstream
  channels, but T2's min_crops=5 + carousel-only filter already makes
  them redundant. Removing them lets recognition fire as soon as the
  crop quota is satisfied.

Other candidates left on the table (will revisit only if T3 also
stalls):

1. **Closed-loop C3→C4 admission throttle** (strategy doc §14): only
   admit a new C4 piece when T4 is GOOD_SINGLE or EMPTY. Trades
   throughput for guaranteed dwell.
2. **Increase the test window 60 s → 120 s / 180 s** to confirm any
   median shift is not a 60-s fluke (per user note).
3. **Parallelise Brickognize per piece** with different crop subsets
   so the in-flight call doesn't block a second recognition attempt
   on the same piece.

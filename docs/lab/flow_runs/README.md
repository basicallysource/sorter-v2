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

### Next experiment T2b (queued)

Hold T2's quality machinery and **lower
`min_carousel_traversal_deg` 15° → 5°**. The trav5 A/B falsified
this in isolation because firing on a single early crop produced 48 %
empty Brickognize results. With T2's min_crops=5 floor we expect the
extra fires to convert into clean classifications instead of empties.

Other candidates (in rough order of expected impact):

1. **Throttle C3 → C4 admission** when T4 is OVERLOADED. Closed-loop
   pattern from strategy doc §14. Less crowding on T4 means more dwell
   per piece. Should raise classified/min toward seen/min without
   needing faster Brickognize.
2. **Lengthen the inter-pulse delay on C4** (slow platter). Direct
   trade-off of throughput vs. dwell. Measure how much dwell per piece
   actually helps the classified rate.
3. **Increase the test window from 60 s to 120 s and 180 s** to confirm
   any apparent win is not a fast-effect fluke (per user note: longer
   windows expose drift, batch effects, warm-up).

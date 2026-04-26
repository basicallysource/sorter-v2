---
title: Operation Target 10 PPM
type: working-note
audience: contributors tuning the live sorter runtime
applies_to: sorter-v2
owner: lab
last_verified: 2026-04-26
section: lab
slug: operation-target-10ppm-2026-04-25
kicker: Lab - Runtime Target
lede: A concrete operating target for the current live tuning phase: ten cleanly classified and distributed LEGO pieces per minute without relying on harsh C4 acceleration.
permalink: /lab/operation-target-10ppm-2026-04-25/
---

## Target

Reach a sustained operating point where the sorter cleanly classifies and distributes **10 pieces per minute** from C4 into the distributor.

Interim target: **8 solid pieces per minute** is a valid near-term operating point if it preserves the single-piece/bin-correctness invariant and does not rely on harsh C4 acceleration.

The target is about stable end-to-end flow, not peak burst speed. A run only counts when pieces are:

1. tracked through the C-channel and C4 runtime path without identity churn causing operational confusion;
2. classified with a usable result;
3. handed from C4 into the distributor;
4. physically delivered without C4 overfill, repeated jams, or obvious pile-up behavior;
5. ejected one-at-a-time into the bin selected for that exact classification result.

## Success definition

| Metric | Target |
| --- | --- |
| End-to-end throughput | >= 10 distributed pieces/min over a measured run |
| Confirmation window | First prove it on short 30-60 s runs, then on 3-5 min runs |
| C3 density | roughly 8-10 visible pieces, not clumped at one exit/intake area |
| C4 density | roughly 8-10 visible pieces, evenly spread enough for tracking and classifier capture |
| Classification | no large backlog of registered-but-unclassified pieces |
| Distributor | no sustained distributor_busy bottleneck or repeated failed handoffs |
| Bin correctness | exactly one C4 piece is released per distributor-ready/commit cycle, into the bin selected for that piece |
| Mechanical smoothness | C4 motion remains audibly and visibly smooth |

## Non-goals

- Do not chase 10 PPM by making C4 acceleration harsh.
- Do not accept high C4 pile-up just because throughput briefly rises.
- Do not tune from UI impressions alone; every change needs a measured before/after.
- Do not reintroduce old tracker stacks for production runtime. BoxMot plus the stable piece layer remains the intended path.
- Do not count a run as successful if C4 ejects trailing pieces into a bin that was positioned for a different classification.

## Preferred tuning levers

Tune in this order:

1. **Backpressure and density**
   - C1 feed cooldown and jam threshold
   - C2 max piece count
   - C3 max piece count
   - C2->C3 and C3->C4 exit handoff spacing
   - C3->C4 virtual slot allowance
   - C4 max zones

2. **Pulse timing**
   - C2 pulse cooldown
   - C3 pulse cooldown
   - C4 transport cooldown

3. **Gentle transport speed**
   - C4 target rpm
   - C4 transport speed scale
   - C4 transport step and max step

4. **Only last: acceleration**
   - Keep C4 transport acceleration conservative by default.
   - Raising acceleration is allowed only for a measured reason and should be rolled back if the motion sounds or looks aggressive.

## Current C4 motion baseline

As of 2026-04-25, the intended C4 baseline is:

| Field | Value |
| --- | --- |
| transport_step_deg | 3.0 |
| transport_max_step_deg | 8.0 |
| transport_cooldown_s | 0.18 |
| transport_target_rpm | 0.7 |
| transport_speed_scale | 4.0 |
| transport_acceleration_usteps_per_s2 | 4000 |
| startup_purge_speed_scale | 4.0 |
| startup_purge_acceleration_usteps_per_s2 | 20000 |
| stepper_degrees_per_tray_degree | 36.0 read-only hardware calibration |

## Current measured candidate

As of the 2026-04-26 early-afternoon pass, the most useful live profile is a cautious C1/C4 flow profile, not the older aggressive C4 density profile:

| Area | Candidate |
| --- | --- |
| C1 | `steps_per_pulse=50`, `microsteps_per_second=1800`, `delay_between_pulse_ms=1500`, `pulse_cooldown_s=2.0`, `startup_hold_s=3.0`, `unconfirmed_pulse_limit=3`, `observation_hold_s=3.0`, `jam_timeout_s=30`, `jam_min_pulses=20` |
| C1/C2 vision gate | `target_low=1`, `target_high=3`, `clump_block_threshold=0.65`, `exit_queue_limit=1` |
| C1/C4 backlog gate | `raw_high=7`, `dossier_high=3` |
| C3 | `max_piece_count=8`, `exit_near_arc_deg=25`, `approach_near_arc_deg=55`, `pulse_cooldown_ms=120` |
| C3->C4 | `slot_capacity=5` |
| C4 density | `max_zones=5`, no `max_raw_detections` cap in the current best profile |
| C4 transport | `transport_step_deg=4.0`, `transport_max_step_deg=10`, `transport_cooldown_ms=140`, `target_rpm=0.9`, conservative acceleration |
| C4 classification / handoff | `classify_pretrigger_exit_lead_deg=160`, `handoff_request_horizon_deg=90` |
| C4 exit approach | `exit_approach_angle_deg=24`, `exit_approach_step_deg=4.0` |
| C4 release | `exit_release_shimmy_amplitude_deg=1.5`, `exit_release_shimmy_cycles=2` |
| Distributor | `simulate_chute=true`, `simulated_chute_move_s=3.5`, `chute_settle_s=0.4`, `fall_time_s=1.5` |

The counterexample matters: `max_zones=10`, tighter `half=6` / `guard=5`, and a wider C3 slot allowance drove C4 raw detections as high as 15 and reduced useful throughput. Overfilling C4 made tracking and classification less stable instead of faster.

The 2026-04-26 counterexamples also matter: capping C4 too hard (`max_zones=3`, `max_raw_detections=5`) reduced distributed throughput, and a faster C4 approach profile (`exit_approach_step_deg=5`, `target_rpm=1.1`) performed worse. A shorter simulated distributor cycle of about 3.7 s did not improve the score either. The current bottleneck is sustained C4 dispatch/backlog balance, not raw distributor wait time and not C4 acceleration.

## Current state, 2026-04-26

The 8 PPM target is not yet proven. The best late-night end-to-end signal from a freshly refilled hopper was `bedtime-fresh-hopper-current-profile-180s`: `+10` distributed during the requested 180 s window, but it ended with C2 overfilled and C4 backlog, so it does not count as "solid".

The follow-up isolated downstream drain, `local-downstream-drain-after-fresh-hopper-c1-held-120s`, distributed `+5` with C1 effectively held. That run proved the current blocker was not the simulated distributor: C4 and distributor drained, while C2 stayed blocked behind C3.

The stationary round/yellow C3 landing-area part was manually removed, and Runtime C3 now has localized bad-actor suppression paths for this failure mode. In `after-round-badactor-removal-and-c3-ignore-120s`, the landing-arc suppression triggered live (`ignored_count=1`) and prevented one stationary track from blocking the C2->C3 lease forever. A follow-up C1 dose loop then exposed a second variant: one C3 track at about `-28 deg` stayed visible after purge, sample transport, and a direct C3 move. Runtime C3 now also quarantines broad C3 transport bad actors after real C3 movement attempts if the track remains angularly stationary, and releases the quarantine again after clear angular motion.

That run still delivered `0.0 PPM`: several active C3 pieces clustered near the upper/landing side and did not move meaningfully toward C4 despite repeated C3 pulses. Treat this as the current local blocker before another full throughput attempt.

Update from the 2026-04-26 late-morning pass:

- C4 no longer advances a classified handoff piece while the simulated distributor is still positioning. The first live verification distributed one controlled piece cleanly.
- C4 now uses gentle approach motion once the distributor is ready, even when the piece is still far from the exit, avoiding the previous "ready but shoved/lost before exit" failure.
- The C4 hardware worker now restarts/reuses queued work robustly after a stale stop sentinel; the previous stuck state was `hw_pending=1`, `hw_busy=false`.
- C4 classification can still happen early (`classify_pretrigger_exit_lead_deg=160` in the current test profile), but distributor handoff requests are now horizon-gated. The best current compromise is `handoff_request_horizon_deg=90`: `60` was safer but starved the distributor; unbounded early handoff caused order thrash.
- C3 transport bad actors no longer freeze upstream at three ignored tracks. The current software block threshold is eight ignored transport bad actors. Five visible non-carrying C3 parts were later drained/distributed instead of freezing C1/C2.
- The current best measured distributed score is **10 distributed in 180 s = 3.33 PPM** (`scored-180s-c1-rhythm2s-low1-handoff90`). That same run classified **26 in 180 s = 8.67 classified PPM**, but it ended with C2/C3/C4 WIP and C4 overfill, so it does not count as 8 solid PPM.
- The honest current conclusion is: **C4 safety/handoff is much better, C1 can feed, and classifier throughput can reach the target band, but sustained distributed throughput is still blocked by C4 backlog/dispatch balance and upstream backpressure.**
- `run_observer.py` post-run drain now must require the whole line to be idle (`C2/C3/C4` runtime and runner counts zero), not merely distributor idle. Older `drained=true` summaries before this change can hide C3/C4 WIP.
- C1 now has a live `feed_inhibit` maintenance gate and an orchestrator C4-backlog gate. This lets downstream local drains happen without fighting new bulk feed, and lets C4 WIP stop C1 before the line turns a good classification rate into an overfilled C4 state.

Update from the 2026-04-26 dynamic live-tuning pass:

- The machine was restarted, homed to `ready`, and visually/camera-checked clean before the dynamic tests: direct C2/C3/C4 detection showed no objects and RT showed C2/C3/C4 empty.
- A conservative 90 s loop (`live-dynamic-cautious-loop-90s`) distributed `+2` and classified `+3`. Flow-gate accounting showed C1 was too conservative: `BLOCKED_C2_VISION_TARGET_BAND` plus `BLOCKED_C2_VISION_EXIT_QUEUE` dominated while C4 was mostly not backlogged.
- Opening C1 live (`target_low=2/3`, `target_high=4/5`, faster C1 pulses) immediately improved feed but rebuilt C4 backlog. The 120 s loop (`live-dynamic-open-c1-loop-120s`) classified `+10` and distributed `+3`; C1 was then correctly stopped by `BLOCKED_C4_BACKLOG_DOSSIERS`.
- The follow-up drain with `feed_inhibit=true` (`local-drain-after-dynamic-open-c1-inhibited`) distributed another `+3`, reached `drained=True`, and ended clean by RT and direct camera detections.
- Current lesson: dynamic live tuning is the right workflow, but the control law needs hysteresis/phase awareness. C1 should be allowed to refill when C4 is genuinely starved, then inhibited quickly when C4 has 2+ dispatch dossiers; otherwise it oscillates between starvation and C4 backlog.

Earlier, the stationary part had remained detected after:

- a 180 s C2/C3/C4 purge attempt;
- direct C3 reverse/forward moves;
- direct C2/C3/C4 detection verification.

Direct detection after that purge timeout:

| Channel | State |
| --- | --- |
| C2 | no object detected |
| C3 | 1 object detected at the C2->C3 landing area |
| C4 | no object detected |

Do not run another throughput test until the tray state has been visually checked again and the C3 clustered/stiction state has either been purged, manually cleared, or deliberately selected as a localized C3 transport test. Any run started from an unintended C3 cluster is invalid for PPM scoring.

Safety update from the 2026-04-26 morning recovery attempt: aggressive maintenance motion can make the C-channel steppers skip and sound rough. Sample transport and direct debug moves are now capped in software, but the operating rule remains stricter than the code: if a recovery move causes skipping, rattling, or harsh circular noise, stop immediately, power-cycle/re-home if needed, and continue only with lower speed/acceleration and shorter local probes.

## Test protocol

Each tuning iteration should be small:

1. Capture `/api/system/status`, `/api/rt/status`, `/api/rt/tuning`, and current C2/C3/C4 track snapshots.
2. Visually inspect the C2/C3/C4 trays before every test.
   - Look at the current camera frames/overlays, not only numeric track counts.
   - Record the physical starting state: empty, lightly loaded, overloaded, clumped, or containing a known bad actor such as a round/stationary piece.
   - Decide explicitly whether to purge, partially drain, manually remove a piece, or keep the state as an intentional loaded-start condition.
   - Do not start a throughput test if the trays do not match the intended starting condition.
3. Use conservative maintenance motion only.
   - Prefer normal runtime pulses or capped sample transport over direct stepper moves.
   - Start local recovery at low speed/acceleration and short duration; scale only after camera evidence shows smooth motion.
   - Do not use long direct moves or high-rpm sample transport as a purge substitute.
   - Stop immediately on skipped steps, rough circular noise, or visible loss of motion authority.
4. Run a short observed test window.
   - Start with 30-60 s while behavior is uncertain.
   - Move to 3-5 min only after C4 flow is stable.
5. Record:
   - distributed pieces/min;
   - classified pieces/min;
   - bin-correct single-piece ejections;
   - any multi-piece tailgating during a single C4 exit release;
   - visual starting condition and purge/no-purge decision;
   - registered piece backlog;
   - C2/C3/C4 live track counts;
   - C3/C4 density and clump symptoms;
   - blocked reasons from runtime status;
   - `flow_gate_accounting` Pareto from the run summary;
   - any audible or visible harsh motion.
6. Change one small cluster of related parameters.
7. Repeat and compare to the previous run.

## Density heuristic

The desired physical state is not "as empty as possible" and not "as full as possible".

Good:

- C3 and C4 show multiple separated pieces across the tray.
- The exits are fed regularly, but not buried.
- Pieces have enough spacing that tracking can hold stable identities.
- C4 has enough candidates to keep the classifier and distributor busy.

Bad:

- C2 stores a pile because the bulk bucket dumped too much at once.
- C3 exit area repeatedly forms a clump.
- C2 or C3 pushes several pieces through an exit in one short burst.
- C4 contains many pieces in one arc and empty space elsewhere.
- C4 must use harsh or frequent recovery motion to keep up.

## C1/C2 burst controller

C1 is not a precision feeder. A single C1 pulse can produce no piece, one piece, a few pieces, or a large clump if the hopper exit releases a packed bridge. Do not tune C1 as though `N` pulses should yield `N` parts.

The intended control model is:

**C1 is a stochastic bulk source. C2 is the measured buffer and first singulator.**

Runtime C2 now exposes a compact density snapshot for the orchestrator:

| Metric | Meaning |
| --- | --- |
| `c2_occupancy_area_px` | Sum of visible C2 bbox areas; a rough burst/load signal. |
| `c2_piece_count_estimate` | Fresh visible C2 track count, including pending tracks. |
| `c2_clump_score` | Simple polar-spacing/cluster score from 0.0 to 1.0. |
| `c2_free_arc_fraction` | Largest empty angular gap as fraction of the platter. |
| `c2_exit_queue_length` | Stable tracks already in the C2 exit/approach queue. |

C1 is allowed to feed only when C2 is low and clean. Current first-pass constants:

| Gate | Value |
| --- | --- |
| target low | `< 1` C2 visible pieces |
| target high | `>= 3` C2 visible pieces blocks C1 |
| clump block | `c2_clump_score >= 0.65` with at least two visible pieces blocks C1 |
| exit queue block | `c2_exit_queue_length >= 1` blocks C1 |
| C4 raw backlog block | `c4.raw_detection_count >= 7` blocks C1 |
| C4 dossier backlog block | `c4.dossier_count >= 3` blocks C1 |

If C2 is in the middle band, C1 holds and lets C2/C3 drain. This intentionally trades a little peak feed aggressiveness for fewer bulk avalanches onto C2 and fewer C2->C3 clump transfers. C1 still also respects transitive C3 and C4 backpressure, so it will not add material just because C2 is low when C3 is saturated or C4 already has a dispatch backlog.

## Stop conditions

Pause or back off immediately when:

- C4 starts visibly overfilling;
- C4 stepper motion sounds aggressive again;
- distributor handoff failures repeat;
- C4 releases more than one visible piece during one distributor-ready/commit cycle;
- a trailing C4 piece falls into the bin positioned for the previous classified piece;
- runtime blocked reasons stay stuck instead of cycling;
- track counts explode relative to visible pieces;
- pieces are being classified but not physically distributed.

## Working hypothesis

The path to 10 PPM is likely not higher C4 acceleration. It is a better density gradient:

**C2 buffers gently -> C3 singulates and spaces -> C4 stays moderately populated -> classifier and distributor remain continuously fed.**

That means the main work is runtime tuning plus observability around density, not simply making each motor faster.

## C-channel singulation invariant

C2, C3, and C4 should all behave like gated exits, with stricter correctness the further downstream a piece gets:

1. C2 should avoid dumping several pieces into C3 at once. It may be a little forgiving, but the next platter should receive separated arrivals rather than bursts.
2. C3 should avoid pushing a short train of pieces into C4. C4 needs spaced arrivals for stable tracking, classification capture, and a clean final ejection queue.
3. C4 is strict: one classified piece, one distributor-ready decision, one physical release attempt.
4. If an exit handoff was just started, the runtime should hold nearby following pieces for a short configurable gap before allowing the next handoff.
5. If the same exit track is still waiting for the downstream side to accept it, the runtime should not create repeated downstream claims for that same track.

## C4 to distributor invariant

C4 must treat the distributor as a per-piece gate, not as an open drain:

1. Once a C4 piece has a classification result, C4 may request a distributor handoff before the physical exit, ideally during the final approach window.
2. The distributor must finish moving to the selected bin and signal ready before C4 releases that piece.
3. A distributor-ready signal authorizes exactly one C4 eject attempt for the matching `piece_uuid`.
4. The exit release should be gentle and narrow enough that only the matched piece falls. If the matched piece is more than half inside the exit zone but does not drop, C4 may use a small exit wiggle for that same piece.
5. The next piece must remain staged behind the exit until it has its own classification result, bin decision, distributor-ready signal, and eject/commit cycle.

Throughput only counts when this invariant holds. A run with 10 physical pieces/min is a failure if multiple pieces ride through one bin decision.

## Open work queue

These are the current known tasks, ideas, and hypotheses while driving toward 10 real PPM. Keep this list compact and update it after each meaningful run or code change.

| Priority | Task / idea | Why it matters | Current next action |
| --- | --- | --- | --- |
| P0 | Fix the active C4 tracked-piece projection truth | Runtime C4 can be empty while `/api/tracked/pieces` still shows old active C4-zone rows. That makes Recent/Tracked and observer queue metrics look unstable or wrong. | Verify and fix the `piece.registered/classified/distributed/lost` projection so delivered/lost C4 pieces become terminal/inactive reliably. |
| P0 | Visually verify tray state before every test | Numeric RT counts can miss the operational reality: leftover piles, clumps, or a round/stationary object can invalidate a run before it starts. | Before each run inspect camera frames/overlays, document the starting condition, and choose purge/partial drain/manual removal/no-purge deliberately. |
| P0 | Treat stationary or non-carrying C3 parts as localized blockers | A part can sit on C3 without moving with the platter, causing correct lease denial or invalid local C1-dose trials. | Runtime C3 quarantines stationary landing-arc tracks and post-transport non-carrying tracks. Validate live with the current stuck C3 object; if this becomes frequent, add a mechanical anti-hook/stiction feature instead of expanding software ghost logic. |
| P0 | Do not blindly score PPM runs while C3 has visible transport bad actors | Ignored C3 tracks keep software flow from freezing, but the physical parts still occupy the tray and can invalidate feed/throughput conclusions. | Observer reports `c3_transport_bad_actor_visible`; C3 now blocks upstream capacity only when the ignored transport cluster reaches 8 pieces. Deliberately decide whether a run is a bad-actor stress test or a clean PPM test. |
| P0 | Make purge success camera-backed | C234 purge can report `cleared` while a fresh camera frame still sees one C2/C3 part shortly afterward. That invalidates automated dose-loop trials. | Observer post-run drain now checks line-idle state, but the maintenance purge coordinator itself still needs camera/runner-backed clear hold. |
| P0 | Use flow-gate accounting before the next tuning change | `downstream_full` hides whether C4 admission, lease spacing, density caps, or distributor readiness is the real blocker. | Compare the `Flow Gate Pareto` in each `run_observer` summary before changing spacing/admission parameters. |
| P0 | Keep enforcing one C4 piece per distributor decision | The 10 PPM target is invalid if trailing pieces fall into the bin positioned for the previous classification. | Keep C4 handoff ordering strict: nearest physical exit candidate only, abort stale handoffs, and only one eject per `piece_uuid`. |
| P0 | Use burst diagnostics to explain multi-arrival drops | When >2-3 pieces appear in a downstream dropzone quickly, we need the upstream motion context, not guesswork. | Review `handoff_burst_diagnostics` after each run and tune C1/C2/C3 exit spacing based on concrete burst records. |
| P1 | Verify the C1/C2 vision burst controller live | Current C1/C2/C3 behavior still oscillates between starvation and clumps. The first C1 gate from C2 density is implemented, but not yet proven in a clean run. | After resolving the current C3 transport/stiction cluster, run a short visual-start test and watch `capacity_debug.c1.controller`, C2 density, and C1 pulse cadence. |
| P1 | Tune C2/C3 singulation earlier in the chain | Every downstream platter is easier when the previous exit avoids short trains of parts. | Keep C2/C3 retry pulses bounded; tune handoff gap, precise pulse size, and escalation separately per channel. |
| P1 | Keep distributor prepositioning, but only in physical exit order | Early handoff requests can hide chute/bin movement time, but wrong ordering creates wrong-bin risk. | Preposition only the nearest classified exit-order piece; never request a trailing classified piece ahead of an unclassified/front piece. |
| P1 | Continue with simulated chute while Waveshare is unreliable | We still need meaningful C4 flow tests even when the real chute controller flakes out. | Use `simulate_chute=true` with realistic move/settle/fall timing, and separately monitor real Waveshare availability before real distribution tests. |
| P2 | Improve observer truth source for C4 queue | The observer currently derives queue symptoms from tracked API data that may be stale. | Prefer runtime C4 dossiers for live queue metrics; use tracked API for history/UI validation. |
| P2 | Add a target-density/clump monitor | The desired state is 8-10 well-spaced pieces, not just a count. | Derive simple per-channel density/clump signals from polar spacing and dropzone-arrival bursts. |
| P2 | Run longer confirmation windows once short runs are clean | Short runs are good for debugging but do not prove sustained target throughput. | After reaching clean >=10 PPM in 60 s, run 3-5 min windows with raw observer evidence. |
| P2 | Re-check BoxMot tracker stability under final density | The current tracker is visually good, but density and burst behavior can still create identity churn. | After flow is stable, rerun the replay/live tracker benchmark on fresh raw crops and verify low churn. |

## Changelog

Real PPM is `distributed delta / requested active run window`. Post-run drain time is tracked in the observer summaries but not counted as active throughput.

| Time | Real PPM | Finding / change | Result / next step |
| --- | ---: | --- | --- |
| 2026-04-25 11:00 | n/a | Defined the operating target as 10 clean classified+distributed pieces/min with smooth C4 motion. | Target and test protocol are now explicit. |
| 2026-04-25 11:10 | 0.0 | Baseline 45 s run after homing: `classified +1`, `distributed +0`; C2 filled to 7-9 pieces while C3/C4 did not establish flow. | Do not tune speed yet; fix flow gating first. |
| 2026-04-25 11:15 | n/a | Found repeated `c3_to_c4 taken=4` while C4 had no matching raw detections/dossiers yet. | Treat as C3 handoff/backpressure issue, not as a C4 acceleration problem. |
| 2026-04-25 11:20 | n/a | Added stale C4 dossier cleanup on RT runtime start. | Prevents old active C4 rows from surviving across tracker epochs/restarts. |
| 2026-04-25 11:25 | n/a | Working fix: debounce C3 downstream claims per `global_id` for the handoff hold window. | Next measured run should show C3 not filling all C3->C4 virtual slots with repeats of the same exit track. |
| 2026-04-25 11:30 | 2.5 | First verification after debounce distributed 2 pieces in 48 s and removed C3->C4 slot spam, but C3 still bunched at the exit while C4 ran empty. | Refined the fix: repeat precise C3 pulses for the same exit track are allowed, but they no longer create duplicate downstream claims. |
| 2026-04-25 11:35 | n/a | Second verification saw C4 raw tracks rise to 6, but C4 dossiers stayed at 1 because the zone guard/half-width geometry is too conservative for the 8-12-piece target. | Added live tuning for C4 zone half-width and guard so density can be tuned without backend restarts. |
| 2026-04-25 11:45 | 6.0 | Dense C4 geometry improved the run to 6 distributed/min, but `c2_to_c3` stayed reserved while C2 held 5-8 pieces and C3 still had headroom. | Applied the same no-duplicate-claim repeat-pulse handoff pattern to C2->C3. |
| 2026-04-25 11:58 | 9.3 | Best pre-restart run: controlled C4 density delivered `+7` in a 45 s requested window. | This became the reference tuning direction: moderate C4 density, not max fill. |
| 2026-04-25 12:02 | 8.0 | Follow-up with slightly faster C4 transport delivered `+6` in 45 s; chute telemetry remained healthy. | C3->C4 and startup/loaded-state effects still dominate; C4 acceleration is not the main lever. |
| 2026-04-25 12:05 | n/a | Live observation: C4/distributor can appear to route several trailing pieces through the bin selected for one classified part. | Added C4->distributor single-piece/bin-correctness as a hard success invariant; next fix must enforce one ready/commit/eject cycle per matched `piece_uuid` and tune the exit release/approach to prevent tailgating. |
| 2026-04-25 12:15 | n/a | Implemented the first software guard for that invariant: C4 now marks `eject_enqueued`/`eject_committed` per dossier, so one distributor-ready piece can only enqueue one physical C4 eject before delivery/finalization. | Unit test covers repeated exit ticks for the same ready piece; next live step is to restart RT and tune the mechanical exit pulse so the one allowed eject does not drag followers. |
| 2026-04-25 12:25 | n/a | Waveshare/controller availability was unstable during live work. | Added distributor chute telemetry (`last_move_*`, `last_position_*`) to RT status so test runs can distinguish a healthy bin-positioning path from blind C4 ejection attempts. |
| 2026-04-25 12:35 | n/a | Replaced the broad C4 legacy eject pulse with a narrow configurable exit-release shimmy. | C4 now releases a matched piece with small forward/back wiggles; UI/API expose release amplitude and cycle count for live tuning against tailgating. |
| 2026-04-25 12:08 | 4.0 | Aggressive C3/C4 density trial after homing delivered only `+3` in 45 s. | Too much C4 loading creates registered-but-unclassified backlog; back off. |
| 2026-04-25 12:10 | 6.0 | Steady trial with aggressive density delivered `+6` in 60 s but hit `raw=15`, `dossiers=8`, and 17 samples with confirmed tracks lacking active dossiers. | Marked as bad direction. Do not use high C4 density as the path to 10 PPM. |
| 2026-04-25 12:12 | 7.0 | Controlled-density run delivered `+7` in 60 s, with `raw=9`, `dossiers=4`, and healthy chute telemetry. | Safer and cleaner than aggressive density, but still below 10/min. |
| 2026-04-25 12:14 | n/a | C1 jam was cleared via `/api/rt/c1/clear-jam`; C1 feed recovered and filled C2/C3 from an empty pipeline. | C1 can feed again, but it can overfill C2 quickly; C1 feed cooldown and jam threshold now need live tuning. |
| 2026-04-25 12:15 | 6.0 | Loaded C3 run delivered `+6` in 60 s and exposed a measurement bug: observer paused while distributor was still `ready/sending`. | Increased observer post-run drain default to 8 s, added grace wait, and record drain result in summaries. |
| 2026-04-25 12:26 | n/a | Added C1 runtime tuning for `pulse_cooldown`, `jam_timeout`, `jam_min_pulses`, `jam_cooldown`, and recovery cycle cap. | Next tuning pass can slow C1 deliberately instead of relying on jam recovery after C2 overfill. |
| 2026-04-25 13:05 | n/a | Found false C4 stitch on `27610dc7cbd6`: black ladder tracklet `86` and white bracket tracklet `90` were merged into one piece. | Tightened C4 same-channel `track_split` stitching to a 1.25 s holdover and a 45 deg hard angle gate; cross-channel C3->C4 transit remains separate. |
| 2026-04-25 13:10 | n/a | Waveshare/chute can be unavailable during tuning, but C4 must still wait as if bin positioning happened. | Added distributor `simulate_chute` runtime tuning with configurable simulated move wait and settle time; one-piece C4 handoff stays enforced. |
| 2026-04-25 13:18 | n/a | C4 could hold a real piece at/near the exit that missed the normal classify angle. | Added late-exit classification fallback; C4 can classify at the exit tolerance before waiting for distributor-ready release, avoiding a safe-but-stuck state. |
| 2026-04-25 13:20 | n/a | Live observation: C3 and even C2 can still feed multiple parts downstream in short bursts, creating clumps before C4 has a chance to separate them. | Added the C-channel singulation invariant and C2/C3 runtime handoff spacing so the system can throttle exits earlier, not only at the final C4 distributor gate. |
| 2026-04-25 13:25 | 6.0 | Best post-fix measured window so far: `slow-c1-moderate-c4-90s` delivered `+9` in 90 s with simulated chute wait. | This is stable enough to keep the single-piece C4 gate, but still below target. The remaining gap is upstream density rhythm, not distributor wait. |
| 2026-04-25 13:28 | 1.5 | A near-empty 8-zone target-profile run showed long starvation, then a late C1 bulk dump into C2 (`piece_count` rose to 10) while C3/C4 were empty. | C1 needs to be treated as a controlled feeder, not just "on when C2 has headroom". Keep C1 slow and jam-tolerant during tuning; add better feed/density control before chasing C4 speed. |
| 2026-04-25 13:30 | n/a | Short live runs showed C4 could resurrect a just-delivered `piece_uuid` from a lingering/rebound track and request another distributor handoff. | Added a short C4 delivered-track tombstone so recently delivered UUIDs/raw IDs cannot immediately become new dossiers again. |
| 2026-04-25 13:34 | n/a | C2/C3 still used large normal advance pulses when multiple pieces were on the ring but none was yet inside the approach arc. | Loaded C2/C3 rings now use precise/gentle advance pulses; single far-away pieces may still use normal transport to avoid unnecessary starvation. |
| 2026-04-25 13:35 | n/a | The first C2/C3 spacing fix was too conservative: if the same front track did not physically arrive downstream, the runtime waited for the long slot hold. | C2/C3 now retry the same front track after the configurable handoff gap, but without taking a second downstream claim; different following pieces still wait. |
| 2026-04-25 13:37 | 3.3 | Verification after loaded-ring precise advance reduced the obvious giant-pulse path but did not yet reach 10 PPM (`+5` in 90 s) and still ended with C2/C3 backlog. | Next lever is a real density controller: throttle C1 by observed C2/C3/C4 counts and add C2/C3 target-density windows, instead of only gating per exit handoff. |
| 2026-04-25 17:40 | n/a | Live state after the previous commit still showed C3 waiting on a front track at the exit while C4 had room, with C2/C3 backlog behind it. | Added same-track handoff retry escalation for C2/C3: after repeated failed arrivals, the runtime may use a bounded double precision nudge without creating another downstream claim. |
| 2026-04-25 17:42 | 2.7 | Retry-escalation smoke run delivered `+2` distributed in 45 s after restart/homing. | Functional, but below target; C4 admission was often blocked by intake/dropzone clearance while C2/C3 refilled. |
| 2026-04-25 17:44 | 6.0 | Loaded retry-escalation run delivered `+9` distributed in 90 s. | Throughput returned to the stable 6 PPM band; remaining blocker is C4 admission closed by dropzone/intake arc, not C3->C4 virtual slots. |
| 2026-04-25 17:51 | 5.0 | Early C4 classification submitted pieces before the exit (`submitted_early=7`) and proved the distributor can be prepositioned during approach, but it also exposed an out-of-order ready state: distributor ready for an older trailing piece while a different piece was physically at the exit. | Fix C4 handoff ordering before the next throughput run; early prepositioning must target the next physical exit candidate only. |
| 2026-04-25 18:01 | n/a | Added C2/C3/C4 handoff-burst diagnostics: rolling recent arrivals, recent move decisions, warning log, RT status snapshot, and observer anomaly surfacing when 3+ arrivals appear in a short dropzone window. | Next runs should capture concrete upstream move context whenever C2->C3 or C3->C4 dumps several pieces in one burst. |
| 2026-04-25 18:01 | n/a | Fixed C4 distributor preposition ordering: C4 now requests the distributor only for the nearest physical exit-order candidate and aborts a stale ready handoff when another piece is actually at the exit. | Unit tests cover ordering and out-of-order abort; restart RT and rerun short controlled windows toward 10 PPM. |
| 2026-04-25 18:04 | 4.0 | First smoke after handoff-order fix delivered `+2` in 30 s, but startup/recovered tracks produced noisy burst diagnostics. | Suppress baseline/recovery false positives so burst logs represent new real downstream arrivals. |
| 2026-04-25 18:06 | 8.0 | Second 30 s smoke delivered `+4`; false-positive burst noise was mostly gone. | Good short signal, but follow-up status still showed C2/C3 burst history and C4 underfeed. |
| 2026-04-25 18:08 | 5.0 | Slower C1 plus single C2/C3 retry pulses delivered `+5` in 60 s and showed C3 stuck waiting for downstream arrival while C4 recovered tracks without releasing C3's slot. | Fix C4 recovered cross-channel transit so C4 can claim pending C3 transit and release the upstream slot. |
| 2026-04-25 18:12 | 7.0 | After C4 recovered-transit release, run delivered `+7` in 60 s and `+10` classified; C4 transit linking improved. | Best current post-fix candidate, but still below target and still shows occasional C2/C3 bursts. |
| 2026-04-25 18:14 | 6.0 | Faster C4 transport (`step=5`, `rpm=1.1`) delivered `+6` in 60 s. | Faster C4 transport did not help; keep C4 smooth baseline and focus upstream rhythm/projection truth. |
| 2026-04-25 18:16 | 3.0 | Allowing double C3 retry nudges delivered only `+3` in 60 s, despite few observer anomalies. | Double nudges are not the current path; return to bounded single nudges and inspect why metrics/Tracked still show stale active C4 rows. |
| 2026-04-25 18:25 | n/a | Live inspection shows runtime C4 `dossier_count=0`, but `/api/tracked/pieces` still reports multiple active C4-zone rows. | Treat projection truth as the next blocker before trusting observer queue metrics or tuning from Tracked UI state. |
| 2026-04-25 18:30 | 1.0 | Hand-off to a fresh debugging pass. Baseline after backend restart fell to 1 PPM because runtime tuning resets to compile-time defaults on every restart, and the doc-recorded controlled-density values were no longer in code. | Move the 9.3-PPM lab values into the code defaults so a homed runtime starts at the right operating point. |
| 2026-04-25 19:14 | n/a | Built a step debugger: pause the orchestrator, step ticks one at a time, inspect dossiers / claims / slot deadlines without spelunking private fields. New API `/api/rt/debug/{pause,resume,step,inspect}`, frontend page at `/dashboard/debug`. | Architecture principles 6 and 7 (introspection + durable debugging). Used immediately to diagnose the slot/admission discrepancies below. |
| 2026-04-25 19:30 | 4.0 | Defaults moved to controlled density (`c3.max_piece_count` 3 → 8, `c4.max_zones` 4 → 9, intake half/guard 10/28 → 7/6). | Confirmed homed runtime now reaches the 4-5 PPM band straight out of restart. |
| 2026-04-25 19:50 | n/a | C4 trailing-piece safety guard added before the exit-release shimmy, anchored on the chute geometry (drop angle ± `exit_trailing_safety_deg`). Without it the shimmy occasionally nudged a second nearby piece off the carousel into the bin positioned for the matched piece. | Prevents wrong-bin double-drops; the operator confirmed the failure mode live. |
| 2026-04-25 20:00 | n/a | Slot system un-gated. Live debugger surfaced repeated cases of `downstream_full` while every CapacitySlot read 0/N empty: a transient claim from an upstream pulse that never produced a downstream arrival held the slot for its 3 s expiry. The orchestrator now sources `capacity_downstream` only from the downstream runtime's `available_slots()`, and `CapacitySlot.try_claim` is permissive (claims still recorded as a debug breadcrumb). | KISS, fewer redundant gates fighting each other. |
| 2026-04-25 20:24 | 4.7 | Operator caught C3 visibly overflowing (~25 pieces, tracker no longer separating them) after I had also removed the C3 cap. Restored the C3 cap as the load-bearing brake; C2's cap stays as the C1 backpressure surface. | Singulation invariant must hold all the way upstream; the cap was not actually a soft hint. |
| 2026-04-25 20:27 | 4.7 | Faster C3 transport (rpm 1.2 → 2.0, exit_handoff_min_interval 0.7 → 0.5) — distributor now ~65% utilized, but C4 still drains too fast between deliveries. | Per-piece distributor cycle is ~5.3 s with the simulated chute (4 s move + 0.3 s settle + ~1 s fall + eject). Theoretical max ~11 PPM. Remaining gap is upstream rhythm keeping a classified piece always ready at C4 exit. |
| 2026-04-26 | n/a | Added runtime flow-gate accounting and run-summary Pareto output so `downstream_full` can be split into concrete causes such as C4 admission, density cap, lease denial, distributor wait, cooldown, or chute singleton guard. | Next run should be a clean 60-90 s baseline using the current controlled-density profile. Accept 8 solid PPM as the first stable waypoint; only then relax C3->C4 spacing or C4 admission. |
| 2026-04-26 | n/a | Distributor servo bus showed intermittent offline errors during homing. Switched live tuning to simulated distributor positioning (`simulate_chute=true`, `simulated_chute_move_s=3.5`, `chute_settle_s=0.4`, `fall_time_s=1.5`) so C4 still waits on the handoff protocol without depending on the unstable physical layer-servo bus. | Treat the next runs as flow/safety runs, not bin-correctness validation. Keep C4 exit-hold safety active and watch for `c4_transport_near_exit_without_distributor_ready` anomalies. |
| 2026-04-26 | 4.0 | `sim-distributor-3p5s-flow-safety` distributed `+4` in 60 s with simulated distributor wait. No `c4_transport_near_exit_without_distributor_ready` anomaly was recorded. Flow Pareto still points at C2/C3 density caps and C4 admission (`dropzone_clear` + `arc_clear`) as the dominant upstream rhythm issue. | Keep the simulated distributor for flow debugging while the servo bus is unstable. Next useful change is not distributor tuning; inspect why C4 has low usable WIP despite C3/C2 being full. |
| 2026-04-26 | n/a | C1 has no explicit startup prime move, but its first normal pulse was allowed immediately after start/resume (`_next_pulse_at=0`) if C2 capacity looked open before perception had settled. | Added a configurable C1 `startup_hold_s` (default 2.0 s) that arms on runtime start/resume and is visible in RT debug/tuning. This should prevent cold-start C1 bulk drops into an already-loaded C2 ring. |
| 2026-04-26 | 1.3 | `c1-20step-start-dose-45s` proved the hold alone was not enough: C1 stacked queued pulses (`pulses_since_progress` jumped to 14) because it checked `hw.busy()` but not `hw.pending()`, and RT was using aggressive jam defaults (`4s/3 pulses`) instead of FeederConfig (`10s/6 pulses/8s cooldown`). | Fixed C1 to block while hardware commands are queued, pass FeederConfig jam values into RuntimeC1, and use a 4.0 s runtime C1 pulse cooldown. |
| 2026-04-26 | n/a | Local C1 dose series after visual clean-start: 12 single 20-step pulses produced no C2 detection; one single 50-step pulse produced one small C2 candidate. | Use 50 steps as the current C1 dose again, but only with the new pending-gate and 4 s observation cooldown. Purge to clean start before the next full-flow run. |
| 2026-04-26 01:55 | 1.3 | C1 progress-observation hold was too short-lived: first C2 progress cleared the hold and allowed follow-up C1 pulses before downstream had stabilized. | C1 progress now extends the observation hold window instead of clearing it; use this to prevent blind post-progress bulk feed. |
| 2026-04-26 02:14 | 1.5 | Clean run with C1 50-step / 3 unconfirmed / 6 s observation showed transitive C1 backpressure working, but C3->C4 admission remained a large blocker. | C1 now also respects C3 density through orchestrator transitive backpressure; next valid clean run should inspect C3->C4 lease/admission in isolation. |
| 2026-04-26 02:22 | 3.3 | Fresh hopper run distributed `+10` in 180 s but ended overfilled (`C2=10`, C4 backlog). Flow Pareto: C1/C2 density, C3->C4 admission arc, and distributor send time all visible; no unsafe C4 release anomaly observed. | Not a solid 8 PPM result. C1 can feed, but the feed controller still oscillates between starvation and overfill. |
| 2026-04-26 02:26 | 2.5 | With C1 effectively held, downstream drain distributed `+5` in 120 s and emptied C4/distributor, but C2 stayed blocked by a C3 landing-area object. | Treat C3 landing-area stationary parts as a separate local blocker before further flow tuning. |
| 2026-04-26 02:30 | n/a | C2/C3/C4 purge timed out after 180 s with C2 clear, C4 clear, and one C3 object still detected. Direct C3 reverse/forward did not move it. | Manual removal or a mechanical anti-hook/recovery feature is required before the next fair 8 PPM test. C2 now reports C3 landing-lease denial as `lease_denied` instead of generic `downstream_full`. |
| 2026-04-26 02:45 | n/a | Added localized C3 bad-actor suppression for physically stationary/rolling-back round parts in the C2->C3 landing arc. It is not a general ghost system: ignored tracks are visible in `upstream_bad_actor_suppression`, do not block upstream landing leases, and become active again after clear angular motion. | Restart backend before the next live test so the runtime loads this code. Validate with a short clean run, watching for ignored-count changes and no C2 freeze on a single stationary C3 landing object. |
| 2026-04-26 09:35 | 0.0 | Restarted backend, homed, verified C2/C3/C4 empty, then ran `after-round-badactor-removal-and-c3-ignore-120s`. The C3 ignore rule triggered live (`ignored_count=1`) and prevented the single stationary landing track from blocking C2, but no pieces reached C4. | New local blocker: several C3 pieces clustered near the upper/landing side did not move meaningfully despite repeated C3 pulses. C1 was put back into held mode; next work should isolate C3 mechanical transport/stiction before more C1 tuning. |
| 2026-04-26 10:00 | n/a | Reframed C1 as a stochastic bulk source instead of a precise dose generator. Added C2 density metrics (`c2_occupancy_area_px`, `c2_piece_count_estimate`, `c2_clump_score`, `c2_free_arc_fraction`, `c2_exit_queue_length`) and an orchestrator C1 gate that feeds only when C2 is low, unclumped, and not already queued at the exit. | Code path is unit-tested. Next live test should happen only after visual tray inspection and the current C3 transport/stiction state is cleared or intentionally isolated. |
| 2026-04-26 10:08 | n/a | Partial local C1 stochastic-dose loop (`2026-04-26_09-49-57_c1-dose-stochastic-loop`): six planned single-dose trials were stopped early. Valid clean-start observations for one 50-microstep-equivalent C1 pulse were `0 parts` then `1 part`; the next observations were contaminated because purge reported clear while the camera still saw a part. | C1 really behaves stochastically at the current dose, but the automated loop must require camera-zero after purge. The last test left C2 clear, C4 clear, and one C3 part at about `-28 deg` that did not clear after 12 s C3/C4 sample transport. |
| 2026-04-26 10:24 | n/a | Added C3 transport bad-actor suppression for physically visible parts that remain angularly stationary after real C3 pulse/sample/purge movement attempts. This is separate from the C2->C3 landing-arc suppressor and is visible as `transport_bad_actor_suppression` in C3 debug. | Restart backend and validate against the current stuck C3 object before restarting any PPM run. A waiting exit piece with downstream closed is explicitly not quarantined by this path. |
| 2026-04-26 10:55 | 1.5 | Clean `c1-single-dose-vision-c4recovered-120s` run distributed `+3` in 120 s. C4 classified/distributed cleanly once fed, but C3 accumulated non-carrying/stationary physical bad actors and C1 delivered too little usable feed. A later aggressive recovery attempt used too-high sample/direct motion values and caused stepper skipping/noise. | Added maintenance safety caps: sample transport now clamps to 8 rpm / 12k max speed / 80k acceleration, and direct debug moves reject excessive degrees/speed/acceleration. Continue with short, low-speed local probes only. |
| 2026-04-26 11:05 | 0.0 | After safe restart and clean C2/C4 state, a cautious C1 50-step flow smoke produced `+4 pieces_seen`, `+1 classified`, `0 distributed`, and left five C3 detections clustered around `-70..-100 deg`. Runtime C3 correctly ignored all five as transport bad actors; a gentle C3-only 2 rpm / 4k / 30k / 20 s sample-transport pass did not move them meaningfully. | This exposed a physical C3 transport/stiction blocker. At the time, three ignored transport bad actors froze upstream; later testing raised that block threshold to eight so localized C3 weirdness can be ignored instead of halting the line. |
| 2026-04-26 11:27 | 1.0 | `post-c4-hold-fix-50step-c1-60s` distributed one controlled piece after C4 requested a distributor handoff at ~49 deg and then held transport until the simulated distributor was ready. | Confirms the "do not shove before distributor ready" fix. Throughput was low because C1/C3 feed was sparse. |
| 2026-04-26 11:32 | 0.0 | `post-c4-ready-gentle-approach-50step-c1-60s` stopped the previous premature C4 push-out, but exposed a worker race: C4 held a ready piece with `hw_pending=1`, `hw_busy=false`. | Fixed `HwWorker` stale-stop-sentinel handling and added C4 `hw_worker` debug. |
| 2026-04-26 11:47 | 1.0 | Local single-piece C2 start distributed `+1` and ended C2/C3/C4 clean. | C4 handoff/distributor simulation is correct for a controlled single piece. |
| 2026-04-26 11:51 | 1.0 | Local C2 cluster drain with C1 held distributed `+2` in 120 s and ended clean. | C2/C3/C4 can drain clusters safely, but not fast enough. |
| 2026-04-26 11:56 | 0.5 | `classify_pretrigger_exit_lead_deg=160` increased classification (`+7`) but only distributed `+1`; early distributor handoffs thrashed/order-changed. | Added `handoff_request_horizon_deg` so early classification does not imply very early distributor reservation. |
| 2026-04-26 12:02 | 0.7 | C2 burst stress test with `handoff_request_horizon_deg=60` distributed `+2` in 180 s. C4 was safe and no out-of-order thrash dominated, but C3 transport bad actors blocked C1/C2 for 137 s. | Raised C3 transport bad-actor upstream block threshold from 3 to 8. This lets localized rolling/stationary parts be ignored without freezing the whole process. |
| 2026-04-26 12:07 | 4.0 | C3 bad-actor threshold smoke distributed `+3` in 45 s from the previously visible C3 parts and ended with C3 clear. | Confirms the higher threshold matches the "ignore localized physical weirdness, do not halt the system" policy. |
| 2026-04-26 12:09 | 1.0 | First scored run with C1 50-step, C4 pretrigger 160, handoff horizon 60 distributed `+2` in 120 s. | Horizon 60 was safe but too conservative; many C4 pieces waited outside the handoff horizon. |
| 2026-04-26 12:15 | 1.7 | Scored 180 s run with C1 50-step, C4 pretrigger 160, handoff horizon 90, and C3 bad-actor threshold 8 distributed `+5`. | Best current post-fix score, still far below 8 PPM. Ended with C3/C4 WIP, proving old observer `drained=true` was misleading. |
| 2026-04-26 12:19 | n/a | C1-held downstream drain after the scored run distributed `+2` and truly emptied C2/C3/C4 by direct detection and runtime debug. | Updated `run_observer.py` so post-run drain requires line idle, not only distributor idle. Next work should focus on upstream rhythm: C1 burst cadence and C2/C3 singulation, not C4 acceleration. |
| 2026-04-26 12:32 | invalid | A scored run after backend restart was invalid because the system had not been homed; C1 state advanced but the stepper was unavailable and no real hardware feed occurred. | After every backend restart, verify `ready`/home before treating any run as evidence. |
| 2026-04-26 12:48 | 3.3 | Best current honest distributed score: `+10` in 180 s with C1 50-step / 2 s cooldown, C2 vision low=1/high=3, C4 pretrigger 160, handoff horizon 90, simulated distributor wait. The same run classified `+26` = 8.67 classified PPM. | Not solid: it ended with C2/C3/C4 WIP and C4 overfill. The target classifier rate is reachable, but C4 dispatch/backlog is not yet controlled. |
| 2026-04-26 12:56 | 2.7 | Tight C4 cap trial (`max_zones=3`, `max_raw_detections=5`, handoff horizon 120) distributed `+8` in 180 s. | Worse than the best run and still left WIP; hard-capping C4 too far starves useful dispatch. |
| 2026-04-26 13:05 | 1.0 | Faster C4 approach trial (`exit_approach_step_deg=5`, `target_rpm=1.1`) distributed `+3` in 180 s. | Faster C4 motion did not help and reduced stability. Revert to conservative C4 motion. |
| 2026-04-26 13:14 | 2.3 | Shorter simulated distributor cycle (~3.7 s total) distributed `+7` in 180 s. | Not better; the main blocker is not simulated chute wait. |
| 2026-04-26 13:25 | n/a | Added live-tunable C1 backpressure from C4 backlog (`c1.c4_backpressure.raw_high`, `dossier_high`) and exposed it through `/api/rt/tuning`. | Use a dynamic live-tuning loop: start conservative, observe C2/C3/C4, then adjust C1/C2 and C4-backlog thresholds in small steps instead of static profile guessing. |
| 2026-04-26 13:28 | 1.3 | First dynamic loop from a clean, homed start used conservative C1/C4 settings and distributed `+2` / classified `+3` in ~98 s. | Too conservative: C1 spent most of the run blocked by one visible C2 part or one C2 exit-queue item while C4 was mostly empty. |
| 2026-04-26 13:30 | 1.4 | Second dynamic loop opened C1 live and used moderate C4 motion. It classified `+10` and distributed `+3` in ~127 s, then C1 was stopped by the new C4 backlog gate (`BLOCKED_C4_BACKLOG_DOSSIERS`). | Confirms the new C4-backlog gate works. The missing piece is a smoother controller/hysteresis that feeds C4 without letting the dossier queue pile up. |
| 2026-04-26 13:33 | n/a | C1 was set to `feed_inhibit=true` and the line was drained. The drain distributed `+3`, reported `drained=True`, and direct C2/C3/C4 detections afterwards were all clear. | Safe stopping point for the next session: machine line is empty, C1 inhibited, and the live-tune evidence points at C1/C4 hysteresis rather than C4 speed. |

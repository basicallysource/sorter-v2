---
title: Operation Target 10 PPM
type: working-note
audience: contributors tuning the live sorter runtime
applies_to: sorter-v2
owner: lab
last_verified: 2026-04-25
section: lab
slug: operation-target-10ppm-2026-04-25
kicker: Lab - Runtime Target
lede: A concrete operating target for the current live tuning phase: ten cleanly classified and distributed LEGO pieces per minute without relying on harsh C4 acceleration.
permalink: /lab/operation-target-10ppm-2026-04-25/
---

## Target

Reach a sustained operating point where the sorter cleanly classifies and distributes **10 pieces per minute** from C4 into the distributor.

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

As of the latest live work on 2026-04-25, the most useful candidate is the controlled-density profile, not the most aggressive density profile:

| Area | Candidate |
| --- | --- |
| C3 | `max_piece_count=8`, `exit_near_arc_deg=25`, `approach_near_arc_deg=55`, `pulse_cooldown_ms=120` |
| C3->C4 | `slot_capacity=5` |
| C4 density | `max_zones=9`, `intake_body_half_width_deg=7`, `intake_guard_deg=6` |
| C4 transport | `transport_step_deg=4.0`, `transport_max_step_deg=10`, `transport_cooldown_ms=140`, `target_rpm=0.9`, `accel=4000` |
| C4 exit approach | `exit_approach_angle_deg=24`, `exit_approach_step_deg=4.0` |
| C4 release | `exit_release_shimmy_amplitude_deg=1.5`, `exit_release_shimmy_cycles=2` |

The counterexample matters: `max_zones=10`, tighter `half=6` / `guard=5`, and a wider C3 slot allowance drove C4 raw detections as high as 15 and reduced useful throughput. Overfilling C4 made tracking and classification less stable instead of faster.

## Test protocol

Each tuning iteration should be small:

1. Capture `/api/system/status`, `/api/rt/status`, `/api/rt/tuning`, and current C2/C3/C4 track snapshots.
2. Run a short observed test window.
   - Start with 30-60 s while behavior is uncertain.
   - Move to 3-5 min only after C4 flow is stable.
3. Record:
   - distributed pieces/min;
   - classified pieces/min;
   - bin-correct single-piece ejections;
   - any multi-piece tailgating during a single C4 exit release;
   - registered piece backlog;
   - C2/C3/C4 live track counts;
   - C3/C4 density and clump symptoms;
   - blocked reasons from runtime status;
   - any audible or visible harsh motion.
4. Change one small cluster of related parameters.
5. Repeat and compare to the previous run.

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
| P0 | Keep enforcing one C4 piece per distributor decision | The 10 PPM target is invalid if trailing pieces fall into the bin positioned for the previous classification. | Keep C4 handoff ordering strict: nearest physical exit candidate only, abort stale handoffs, and only one eject per `piece_uuid`. |
| P0 | Use burst diagnostics to explain multi-arrival drops | When >2-3 pieces appear in a downstream dropzone quickly, we need the upstream motion context, not guesswork. | Review `handoff_burst_diagnostics` after each run and tune C1/C2/C3 exit spacing based on concrete burst records. |
| P1 | Build a real density controller, not just fixed thresholds | Current C1/C2/C3 behavior still oscillates between starvation and clumps. | Control C1 feed and C2/C3 handoff pacing from observed C2/C3/C4 counts and blocked reasons. |
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

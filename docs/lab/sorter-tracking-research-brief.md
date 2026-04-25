---
title: Sorter Tracking — Research Brief
type: research-brief
audience: external researcher / second opinion / deep-research input
applies_to: sorter-v2
owner: lab
last_verified: 2026-04-25
section: lab
slug: sorter-tracking-research-brief
kicker: Lab — Research Input
lede: Self-contained fact sheet on the LEGO sorter's hardware, perception stack, observed behaviors, and the open question — what is the right tracking + dispatch architecture given that pieces move unpredictably on the rotating platters and the bulk feeder dispenses irregularly?
permalink: /lab/sorter-tracking-research-brief/
---

## What we are trying to do

Sort loose, unsorted LEGO pieces from a bulk hopper into ~140 destination bins with **>= 10 cleanly classified and distributed pieces per minute**, without dropping multiple pieces into the wrong bin per ejection cycle. The end-to-end success criterion is per-piece bin-correctness, not raw throughput.

## Physical setup (the hot path)

```
Bulk hopper -> C1 (feeder rotor) -> C2 ring -> C3 ring -> C4 platter -> Distributor chute -> Bin
```

- **C1 — Bulk feeder rotor**: a rotor that drops pieces from a bulk hopper onto the C2 ring. Pulse-based: each pulse advances the rotor a fixed step. Output count per pulse is **highly variable** (zero pieces, one piece, or several at once depending on what is sitting against the wall). Operator cannot reliably predict pieces-per-pulse.
- **C2 — first ring (large platter)**: rotating tray, about 60 cm diameter, holding loose pieces. One physical drop edge over to C3.
- **C3 — second ring (smaller platter)**: rotating tray, about 40 cm diameter. One drop edge over to C4.
- **C4 — classification platter**: rotating tray, about 25 cm diameter. One classification camera looking down. One drop edge over the distributor chute.
- **Distributor chute**: positions to one of ~140 bins; one piece falls per "ready -> commit" cycle.

All four rotating elements are **flat, friction-driven** — pieces sit loose on the tray, no pockets, no carriers, no escapement mechanism. Pieces can slide, tumble, get nudged by the next piece, or stick momentarily to debris on the tray surface.

## Drive hardware

- Steppers with microsecond-precise position feedback (we know the **tray angle** at any time within sub-degree accuracy).
- We do **not** know an individual piece's angle from the encoder alone — only the tray angle. A piece on a friction-driven flat tray can drift relative to the tray.
- Motion API is "rotate by N degrees with profile X". No position feedback from the piece itself.

## Perception stack

- **One RGB camera per ring** (C2, C3, C4), top-down view of the tray.
- **Detector**: YOLO11n / YOLO11s, single class "lego_piece", running at 5-15 fps depending on ring.
- **Tracker**: BoxMot ByteTrack as the live tracker, plus a shadow `botsort_reid` running with OSNet appearance embeddings for cross-channel re-identification.
- **Cross-channel re-id**: a `TransitStitcher` uses OSNet embeddings to stitch C3->C4 transit (a piece leaves C3's view briefly while sliding down to C4 and re-enters with a fresh raw track ID; we want to recognize it as the same piece).
- **Classification**: a separate classifier (Brickognize or local model) runs on a single cropped frame at the C4 classify-trigger angle.
- **Tracker IDs are not stable** across long pauses, occlusions, and cross-channel transits. The shadow OSNet helps but is not perfect.

## What pieces actually do on the trays (observed)

1. **Variable feeder dispense**: C1 sometimes gives 0, 1, 2, or 5+ pieces per pulse. Bursts of pieces hitting C2 at once are routine.
2. **Different per-piece velocities on the tray**: a flat 1x1 plate slides differently than a heavy technic axle. Pieces near the inner edge travel slower than those near the outer rim. Pieces resting against the tray wall move with the tray; pieces in the middle can drift radially.
3. **Inter-piece collisions**: a faster piece can catch up to and nudge a slower one — net effect is one of the two suddenly **changes velocity and possibly angle** mid-channel, with no warning.
4. **Clumping**: at the exit of C2 / C3, pieces line up against the drop edge. Two or three pieces can ride the edge simultaneously; one push moves all of them across.
5. **Tumbling**: a tall piece (e.g. minifigure leg) can tip over, changing its bbox shape and confusing both the detector and the tracker.
6. **Identity loss**: when a piece slides out of frame momentarily (passing over a drop edge, behind a tray rim) the tracker often re-issues a fresh raw ID on re-acquisition.
7. **False positives**: small surface irregularities (scratches, tape, stickers on the empty tray) sometimes register as low-confidence "pieces" — these are filtered by `confirmed_real`, but during the live run we still see ghost tracks pollute the count.
8. **Detector misses**: a piece at an awkward angle or partly occluded under another piece may be missed for several frames, then re-appear with a new ID.

## What the runtime actually does today

- Per-channel runtime (`RuntimeC1/C2/C3/C4/Distributor`) ticks at ~50 Hz; each runtime decides what motion / handoff to dispatch this tick based on visible tracks + downstream capacity signal.
- C2 / C3 / C4 each have a `max_piece_count` cap; if the visible action-track count is at the cap, the runtime reports `available_slots = 0` and the upstream channel idles.
- C4 has a `ZoneManager` that records an angular zone per admitted piece; admission denies new pieces if the intake arc or drop arc currently overlaps an existing zone.
- C4 classifies a piece a configurable lead before the exit angle; the result is bound to a `_PieceDossier` keyed by `piece_uuid` and `tracked_global_id`.
- Distributor is positioned ahead of time on the **front exit-order candidate**; once chute is `ready`, C4 fires a small forward-back shimmy (~1.5 deg amplitude) to nudge **the matched piece** off the tray edge.
- A trailing-safety guard refuses the shimmy if any other owned track sits within the chute window at the same instant.

## Where we are on throughput right now

- Best stable post-fix run: **4.7 PPM** with the 4 s simulated chute (theoretical ceiling ~11 PPM at that chute timing).
- Distributor utilization in those runs: ~65%. The remaining 35% is C4 starvation (no classified piece ready at exit when chute finishes its previous cycle).
- Per-piece end-to-end timing (registered -> distributed) was measured at 6 s best case, 22-27 s worst case in the same run. The worst-case pieces are ones that wait through one or more distributor cycles for trailing pieces to clear the chute window.

## Observed failure modes that gate higher throughput

1. **C4 admits 1-3 dossiers when 12-15 raw tracks are visible**. Most of those tracks never become operator-visible pieces because the admission gate (`arc_clear` / `dropzone_clear`) refuses while another zone overlaps.
2. **Trailing-piece-in-chute event is common after a C3 burst**. C3 occasionally pushes 2-3 pieces across the C3->C4 drop edge in a short window. They land within 5-10 deg of each other on C4, and the trailing-safety guard then defers their ejects until they separate — which on a friction-driven flat tray they sometimes never do, so they get rotated past the chute and lost.
3. **Tracker identity churn under density**. With C3 carrying >10 visible pieces, BoxMot starts re-issuing track IDs for the same physical piece between frames. The C4 cross-channel stitcher catches some of these via OSNet, but not all.
4. **Distributor `ready` waits 2-6 s for C4 to actually eject**. Live runs showed pending pieces sitting in `ready` while the matched piece was still slowly approaching the exit. C4's transport at 0.9-1.3 RPM is slower than the 4 s chute cycle for far-from-exit pieces.
5. **Pieces lost without traversing the pipeline**. A piece can enter C4, reach the classify angle, get classified, and then never reach the exit-eject zone because (a) it was deferred by trailing-safety, (b) its track went stale and the dossier was finalized as `track_lost`, or (c) it was overtaken in exit ordering by a different piece.

## What we have already tried (this session)

- Step-debugger built (pause orchestrator, step ticks one at a time, inspect every dossier / claim / slot). Available at `/api/rt/debug/{pause,resume,step,inspect}`.
- `CapacitySlot` system effectively decommissioned: the orchestrator no longer ANDs the slot's claim count into capacity_downstream; `try_claim` is permissive. The slot remains as a debug breadcrumb.
- C4 trailing-piece safety guard (default 14 deg, anchored on chute geometry).
- Default tuning moved to controlled-density (`c4.max_zones=9`, `c3.max_piece_count=8`, `c2.max_piece_count=5`).
- C2 + C3 caps **kept** as the upstream backpressure surface; removing the C3 cap caused live overflow with the tracker losing identities entirely.

## Constraints that matter for any new architecture

- **Real-time, on-device**: runtime ticks at 50 Hz, perception runners at 5-15 fps. Backend runs on a host PC (currently macOS for dev, Linux SBC for production). YOLO inference cost is the dominant compute load.
- **No retrofitable mechanical singulation**: we are not adding star wheels, escapement gates, vibratory bowls, or pucks. The platter is the platter.
- **Encoder by itself is insufficient**: the tray angle is known; the per-piece angle is not. Pure encoder-anchored prediction breaks within seconds when a piece slides or gets nudged.
- **Vision must remain primary** for piece position, but it is noisy: detector misses, tracker churn, ghost tracks, and cross-channel ID resets all happen routinely.
- **Distributor is a hard one-piece-at-a-time bottleneck** (4 s simulated chute today, real Waveshare chute target similar), so the upstream pipeline only needs to keep one classified piece always ready at the C4 exit and never deliver multiple at once.

## The actual research question

Given:

- a friction-driven rotating tray where pieces move unpredictably,
- a noisy upstream feed that bursts irregularly,
- a vision + multi-object tracker (BoxMot ByteTrack + OSNet shadow) that is the only source of per-piece position,
- a downstream actuator that costs ~5 s per cycle and must consume exactly one piece per cycle,

what is the right software architecture for **piece-tracking + dispatch decisions** so that:

1. each admitted piece's identity holds stably from intake-on-C4 through eject-into-bin, even under density and brief occlusion;
2. the system can predict — well enough to act — when a specific identified piece will arrive at the exit zone, despite per-piece velocity variation;
3. the C3 -> C4 handoff produces pieces with at least chute-width spacing on C4, so the trailing-safety guard rarely needs to defer;
4. the distributor stays close to fully utilized without ever delivering more than one piece per cycle into the wrong bin?

## Industrial reference patterns we have considered (and their fit)

- **Encoder-anchored carrier tracking** (cross-belt sorters, tilt-tray, star wheels): excellent when the piece is rigidly bound to the carrier. **Does not transfer** to our friction tray.
- **Time-of-flight gates** (multi-station belt with predictable transit time): partially applicable — we can replace the `pending_downstream_claims` machinery with "did the piece arrive at the next ring within `t_expected ± tol`", but the tolerance has to be wide because the piece-velocity variance is wide.
- **Decision-at-induction** (one classify, one identity, no re-decisions): partially applicable — the classification is already one-shot, but the dispatch decision currently re-resolves "which piece is at the exit" via vision rather than trusting the bound dossier.
- **Vision + encoder hybrid as prior + correction** (pick-and-place over conveyor): this is closest to where we want to land. Vision is truth, encoder is a soft prior used to bridge the gap between vision frames and to weight tracker re-acquisitions ("the piece that disappeared 0.5 s ago should now be at angle X +- delta — does any new track match that prediction?").
- **Vibratory bowl + escapement** (pharma / packaging singulation): not retrofitable mechanically. The closest software analog is a **logical escapement**: C3 only releases the next piece toward C4 once the previous arrival is at least N degrees down the C4 arc — a per-piece spacing guarantee enforced at the handoff, not at the exit.
- **Reject-on-doubt** (no-read reject in postal sortation): we already do this implicitly via the `reject` bin. We do not yet route track-identity-uncertain pieces to a re-circulate path; in our case "re-circulate" would mean leaving the piece on the tray for one more revolution.

## What a useful answer looks like

Concrete recommendation for **how to combine BoxMot tracker identity, encoder rotation, and vision detections into one coherent per-piece state model** that:

- holds identity stably under tracker churn (already half-solved by OSNet appearance gating),
- gives a position estimate accurate enough to dispatch to within ~5 deg, with explicit uncertainty,
- supports a logical escapement at C3->C4 that guarantees physical spacing on C4,
- reduces YOLO load because vision is consulted as a corrector, not as the per-tick truth,
- and degrades gracefully when a piece's vision identity is lost — the system either reject-routes it or accepts the loss without poisoning the rest of the pipeline.

Bonus value: pointers to algorithms or papers that have solved the "tracker over a noisy carrier with per-target velocity variation" problem — our hunch is that the literature on **multi-object tracking with motion priors** (Kalman with measurement-confidence weighting, or Bayes filter over per-piece motion model) covers exactly this case.

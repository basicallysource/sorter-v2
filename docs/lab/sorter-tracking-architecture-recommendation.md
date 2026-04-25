---
title: Sorter Tracking — Architecture Recommendation
type: architecture
audience: contributor reference
applies_to: sorter-v2
owner: lab
last_verified: 2026-04-25
section: lab
slug: sorter-tracking-architecture-recommendation
kicker: Lab — Architecture Direction
lede: Vision-corrected virtual-pocket architecture for the C-channel pipeline. PieceTrackBank with durable UUIDs owns the dossier; BoxMot/ByteTrack/OSNet/encoder/detections become measurements. C3 acts as a software escapement, C4 as a sparse clocked buffer.
permalink: /lab/sorter-tracking-architecture-recommendation/
---

## Origin

External research input answering the open question in [`sorter-tracking-research-brief`]({{ '/lab/sorter-tracking-research-brief/' | relative_url }}). Captured here verbatim because the architectural direction it lays out is the intended target for the next refactor pass.

## Core recommendation

Build the sorter around a **vision-corrected virtual-pocket architecture** on C4.

The durable object is not a BoxMot/ByteTrack raw track ID. It is a **physical-piece UUID** maintained by a higher-level `PieceTrackBank`. ByteTrack, BoT-SORT/OSNet, detector boxes, and encoder angle become **measurements and association hints** into that bank. The bank owns the dossier, classification, uncertainty, exit ETA, and dispatch eligibility.

The second key change is architectural: **do not try to make C4 robust under burst density.** Use C3 as a software escapement so C4 becomes a sparse, clocked buffer.

> Treat C4 as a pocketless sorter with "virtual pockets": each admitted LEGO piece has a UUID, a Bayesian state estimate, a covariance ellipse/arc, a reserved angular gap, and an exit-time distribution; C3 only releases into a granted gap, and the distributor only fires when the posterior says exactly one classified UUID is in the chute window.

## Four-layer separation

### Layer A — sensors

```
YOLO detections
BoxMot / ByteTrack raw tracklets
shadow BoT-SORT / OSNet embeddings
camera calibration
encoder angle phi(t)
motor profile commands
```

### Layer B — physical piece estimator

```python
PieceTrack:
    piece_uuid
    channel
    state_mean          # polar tray-frame state
    state_covariance    # explicit uncertainty
    mode_probs          # carried / sliding / collision / edge-transfer
    p_exists
    p_identity_stable
    p_confirmed_real
    raw_track_aliases
    embedding_mean
    color_shape_signature
    class_label
    class_confidence
    lifecycle_state
    reserved_zone
    exit_eta_distribution
```

BoxMot IDs become aliases inside `raw_track_aliases`, not durable identities.

### Layer C — C3 to C4 admission / logical escapement

C3 asks: "Can C4 grant a future landing gap for one piece? Is exactly one C3 candidate positioned for release? Is the follower distance behind that candidate large enough?"

If yes, release one piece and create a pending C4 birth prior. If no, hold, reverse, or run another separation pass.

### Layer D — distributor scheduler

Dispatches a specific `piece_uuid` only if all five conditions hold:

```
P(target UUID in chute window) is high
P(any other known/unknown piece in chute window) is low
classification is bound to that UUID
identity association entropy is low
exit-angle uncertainty is below threshold
```

## Tray-frame polar tracking with encoder as control prior

```
theta_cam = atan2(y - cy, x - cx)
r         = sqrt((x - cx)^2 + (y - cy)^2)
a_i(t)    = wrap(theta_cam(t) - phi(t))
```

State `x_i = [a_i, r_i, adot_i, rdot_i]`. Predict between vision frames; correct on detection. Encoder is the carrier prior, not the piece position.

For dispatch, compute exit-angle distribution:

```
mu_exit_angle, sigma_exit_angle
mu_eta,        sigma_eta
P(arrival within commit window)
```

For ~5 deg dispatch accuracy: `3*sigma_theta <= 5 deg`, so `sigma_theta <= ~1.7 deg`.

## IMM-style mode-switched motion model

| Mode | Meaning | Process noise |
|---|---|---:|
| carried | piece moves with tray, tray-frame angle near constant | low |
| sliding | piece has stable tray-relative drift | medium |
| collision_or_clump | neighbour overlap, sudden residual, tumble | high |
| edge_transfer | near C3 to C4 intake or C4 exit edge | high / special |
| lost_coast | no detection but expected to exist | growing with time |

Trigger heuristics:

```python
if overlap_with_neighbor or sudden_residual or bbox_shape_jump:
    mode = collision_or_clump
    inflate_covariance()
elif several clean updates with small residual:
    mode = carried or sliding
    reduce_covariance_gradually()
```

Calibrate process noise from logged residuals binned by radius, piece size, aspect ratio, RPM, density, recent-collision flag, edge proximity. If 95% of detections fall outside the 2-sigma gate, the model is lying.

## Gated multi-cue association

```
cost(i, j) =
    MahalanobisDistance(position_j, predicted_position_i)
  + lambda_app   * (1 - cosine_similarity(OSNet_j, embedding_i))
  + lambda_shape * shape_distance(j, i)
  + lambda_color * color_distance(j, i)
  + lambda_rawid * raw_track_alias_penalty
  - lambda_conf  * detector_confidence
```

Hard gates before assignment: position inside covariance gate, plausible appearance, not a known static ghost. Hungarian for normal cases; PDA/JPDA or bounded MHT for ambiguous local clusters.

## C3 to C4 as a leased handoff

The highest-leverage change.

C3 does not release because C4 has capacity. C3 releases because C4 granted a **future landing lease**.

```
S_min = W_chute + k*(sigma_leader + sigma_follower) + mechanical_margin
```

Start around **30-45 deg effective spacing** on C4; tune down only after logs prove covariance calibration.

C4 speed 0.9-1.3 RPM = 5.4-7.8 deg/s. 10 PPM = one piece every 6 s = 32-47 deg of C4 travel between pieces. So **8-11 cleanly spaced pieces per revolution** is the right C4 buffer for 10 PPM.

C3 release rules:

```
exactly one owned/visible candidate in release arc
no second candidate within follower danger arc
candidate has acceptable position uncertainty
C4 has granted a landing lease
->
create PendingBirth(piece_uuid, predicted C4 landing prior)
pulse C3
wait for C4 confirmation inside time/angle gate
```

If C4 sees two arrivals in the gate: do not pick one with OSNet. Mark handoff as failed, no normal-bin dispatch, tighten C3 release constraints.

## Dispatch by posterior exclusivity

For each C4 piece at time t:

```
I_i(t) = [
    mu_theta_i(t) - k*sigma_theta_i(t) - piece_extent_i/2,
    mu_theta_i(t) + k*sigma_theta_i(t) + piece_extent_i/2
]
```

Eject only if target interval overlaps chute window AND no other interval does AND classification bound AND identity confidence high.

```
E_i(t) = P(piece_i in chute_window at t)
       * P(no other piece in chute_window at t)
       * P(identity_i is stable)
       * P(class_i is correct enough)

commit if E_i(t_commit) >= threshold and sigma_exit_angle <= sigma_max
```

Targets: `sigma_max ~ 1.5-2.0 deg`, `P(singleton) >= 0.98 or 0.99`.

## C4 as a clocked buffer

C4 knows the chute's next free time and selects a classified UUID + motion profile so the chosen piece arrives near `t_free`. Scheduling problem, not a tracker problem.

```python
if distributor_busy:
    preposition chute for next high-confidence UUID
    shape C4 motion so UUID arrives just after chute_ready

if distributor_ready:
    only shimmy if posterior singleton condition is met
    otherwise no-shimmy and recirculate / reject-when-isolated
```

## Vision as corrector, not 50 Hz truth

50 Hz runtime: predict tracks, update ETAs, update reservations, make motion decisions. YOLO at 5-15 FPS provides corrections.

Reduce load:

1. Full-frame YOLO for births / intake zones / periodic sanity checks.
2. Predicted ROIs for existing high-confidence pieces.
3. OSNet embeddings only at birth, re-ID ambiguity, handoff confirmation, pre-dispatch sanity check.
4. Low-score detections recover existing tracks, never create confirmed births.
5. Tray-frame static ghost map prevents scratches/tape/stickers becoming births.

## Explicit degradation states

```
TENTATIVE_GHOST_OR_BIRTH
CONFIRMED_UNCLASSIFIED
CLASSIFIED_CONFIDENT
CLASSIFIED_BUT_IDENTITY_UNCERTAIN
LOST_COASTING
CLUSTERED_WITH_OTHER_PIECE
REJECT_ONLY
EJECTED_CONFIRMED
DROPPED_OR_FINALIZED_LOST
```

Hard rules:

- Unknown pieces block the chute window.
- Unknown pieces do not get normal-bin dispatch.
- Classified-but-identity-uncertain pieces do not get normal-bin dispatch.
- Clustered pieces are not single-piece eject candidates.
- Lost tracks age out only after their covariance/position can no longer poison dispatch.

> Safety invariant: a track may lose its right to be sorted into a class bin, but it must not lose its ability to block the chute while it might physically be there.

## Phased rollout

### Phase 1 — `PieceTrackBank` on C4 in shadow mode

Run alongside the current system. Log raw track ID, piece_uuid, predicted theta_exit, actual measured theta, sigma_theta, association decision, classification binding, eject decision, reason for reject/defer.

**First success metric is not PPM. It is: are 95-99% of later detections inside the predicted uncertainty gate?**

If no, fix the motion model and process noise before anything else.

### Phase 2 — replace C4 dispatch authority

Keep the current detection/tracker stack. Stop dispatching from raw exit-order candidates. Dispatch from `piece_uuid + posterior singleton condition + class binding`. Reduces wrong-bin risk before throughput improves.

### Phase 3 — C3 handoff lease

Throughput unlock. C4 should hold around 8-11 cleanly spaced classified pieces per revolution.

### Phase 4 — adaptive C4 motion

Use C4 speed/profile to align the next classified UUID with the distributor's free time.

## Algorithm references

| Problem | Family | Fit |
|---|---|---|
| Low-confidence detections during partial occlusion | ByteTrack low-score association | Good measurement recovery, not durable identity |
| Identity through short occlusion / tracker churn | DeepSORT / BoT-SORT motion + appearance | Pattern, not identity owner |
| Non-linear motion / occlusion correction | OC-SORT observation-centric | Avoids overtrusting predictions |
| Ambiguous detections, ghosts, missed detections | PDA / JPDA | Soft association |
| Reversible ambiguous identities | MHT / N-scan pruning | Bounded, real-time |
| Carried/sliding/collision regimes | IMM / multi-model Kalman | Right motion model |
| Formal labeled multi-object Bayes tracking | delta-GLMB / LMB / labeled RFS | Heavy — only if C4 stays dense |
| Appearance embedding | OSNet | Useful cue, fine-tune for LEGO |

## Bottom line

```
C2/C3 = messy reservoir
C3    = software escapement / metered release
C4    = sparse vision-corrected virtual-pocket buffer
tracker IDs   = sensor hints
piece UUIDs   = durable truth
encoder       = carrier prior
vision        = correction
scheduler     = posterior-risk controller
distributor   = commit only on singleton certainty
```

The most important safety rule:

> Never let uncertainty disappear just because identity disappeared.

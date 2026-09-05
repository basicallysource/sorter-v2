# C4 indexed buffer

Status: opt-in implementation, tested with simulated camera/motor sequences.
Not commissioned on hardware. The default remains `two_piece_state_machine_rev01`.

## Behavior

`indexed_buffer_rev01` reserves the five physical 72-degree pockets. Captured
parts can advance while earlier recognition requests or chute positioning are
still pending. There is no two-part queue limit; admission permits at most four
reserved pockets, and the actual usable capacity is further constrained by the
landing arc, outlet geometry and occupied-pocket clearance.

Each move advances at most one pitch. The leading wall of every unreleased
pocket must remain at least five degrees short of the calibrated exit boundary.
A shorter safe move is allowed; a later move completes the remaining index.
The distributor owns one head at a time. Output permission requires its exact
KnownObject in the positioning slot, distributing stage and distribution-ready
signal. The next pocket remains protected during discharge.

A stopped, empty landing pocket can admit another part independently of the
head's recognition state. Before motion, admission closes, C3 must be stopped,
and a one-second settling interval allows an already falling part to arrive.
All reserved parts must finish capture before motion. A ready head drains after
the existing three-second no-successor grace. At the outlet, further movement
uses bounded five-degree nudges with a finite travel budget.

## Identity and exit confirmation

Reservations survive missing camera tracks indefinitely. A new ID may recover
the part in its physical pocket; IDs cannot migrate between reserved pockets.
Two boxes in one pocket, an untracked box, or a box crossing/approaching a divider
holds the flow. Oversized parts and double arrivals currently require inspection;
there is no automatic combined-pocket or multiple-part rejection flow.

An exit requires observing the head reach the output boundary, then at least
0.5 seconds of fresh frames with that identity absent and the exit arc empty.
A commanded angle, vanished upstream ID, or elapsed timeout cannot commit it.
The destination remains reserved until confirmation. If the camera misses the
entire passage across the edge, this conservative implementation holds for
inspection instead of assuming delivery.

Whole-channel auto-clear and manual stall wiggle are disabled in this mode:
they could sweep differently classified parts into one bin. Missing reservations
still count as occupied for the stall watchdog, even if the camera sees nothing.

## Optical reference and startup

Start with an empty, aligned platter. Unlike the earlier rev01 startup, this
mode does not purge the platter by rotating it. It requires an empty camera
view for one second before establishing an optical divider reference.

The wall detector uses the saved arc center and outer radius, scaled uniformly
to the camera frame. At least three independently observed walls must agree
with a regular five-pocket rotor within three degrees. Competing grids are
rejected; fragmented edges of one wall cannot outweigh independent walls.
The reference center must agree with the perception service within 20 pixels. After each movement,
a frame captured after the motor stopped must confirm the expected divider
phase within five degrees. A failed motor acknowledgement latches a hold.
The landing arc, including a five-degree guard, must lie in one empty pocket.
An unaligned empty platter is held for alignment rather than moved blindly.

Phase is unwrapped using the commanded displacement. The wall pattern alone
cannot distinguish an error of exactly one pitch. Optical residuals, actual
travel direction, landing-to-outlet geometry, tolerances and motor slip need
hardware validation before this mode can be considered production-ready.
Camera data older than one second closes admission and prevents new moves.
Cleanup/resume requires an empty platter and a new reference.

## Configuration and diagnostics

Select **Five-pocket buffer (experimental)** in the classification mode settings,
or set the machine configuration:

```toml
[classification_channel]
mode = "indexed_buffer_rev01"
```

The existing rev01 capture, recognition and movement-speed settings apply.
Perception-native feeder modes are supported. Use a fresh runtime after changing
mode; never switch a loaded platter into the new mode.

`GET /api/classification-channel/buffer-status` reports whether this controller
is active and its cached phase, admission gate, divider phase, requested move,
and each pocket's track, capture/result state, positioning ownership and exit
gap. Reads do not run inference or issue motor commands. Blocking reasons also
appear in the backend log with `[C4-INDEXED]`.

## Validation and commissioning still required

Automated tests cover three-part buffering with a pending head classification,
whole-pocket bounds in both travel directions, next-pocket protection on eject,
partial indexes, single-part drain, confirmed exit and successor ownership,
missing/changed IDs, divider-straddling boxes, double arrivals, pending captures,
C3 motion, stale frames, wrong/busy distribution ownership, failed motor commands,
optical disagreement, cleanup/restart and inhibited bulk recovery.

The wall detector has been revised against real camera images. Its former
brightness-based enclosing circle included the bright workbench. The revised
path uses calibrated geometry and line direction, caps processing width at
960 pixels and checks independent wall support and residuals. In eight empty
rotor preview frames, the maximum per-frame grid residual changed from
6.5–11.8 degrees to 0.2–1.3 degrees; all five walls were detected each time.
This measures grid consistency, not surveyed absolute accuracy. A 12-run
isolated ARM benchmark on one 960x540 fixture returned valid results every
time, at about 212 ms median per evaluation. The service was not replaced.

Perception's inference crop is mapped back into full-frame coordinates;
`read_bboxes_and_frame` returns the full camera frame, not the model crop.
The API and controller now share the same calibrated geometry conversion.
Missing calibration only permits the old image-circle fallback for a complete,
isolated disc on a dark background; clipped/bright-background fits fail closed.

Another commissioning constraint remains: the current capture/drop arc is
about 123 degrees wide, larger than one 72-degree pocket. A distinct measured
landing footprint is required before indexed admission can open. Do not simply
shrink the capture zone to make a check pass. No throughput or physical sorting
accuracy improvement has yet been measured for this controller.

Commission with a counted batch at two occupied positions, then increase only
to capacity verified on the real inlet-to-outlet arc. Compare correct physical
bin arrivals per elapsed minute, wrong-bin count, rejects, missing/duplicate
records and manual interventions against the existing controller. Include
small parts, large parts, sparse feed and interrupted/restarted runs.

## Accompanying corrections to the existing controller

- Spatially bounded, unambiguous re-identification and orphan recovery.
- Keep the original recognition after a retry timeout; normal/high-value bin
  selection requires `classified` status.
- Retain the destination after an eject timeout; commit forced recovery only
  after the channel-clear operation succeeds.

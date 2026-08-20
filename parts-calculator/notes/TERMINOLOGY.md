# Sorter terminology & part notes (for the agent)

My working notes so I use the right words and quantities. Not shown in the app.
Source of truth for the calculator is `slicer/parts.json`; this explains the *why*.

## The machine, top to bottom

- **Feeder** — feeds pieces in. Sits on top. Built from **C-channels** (there are
  **4 C-channels**). One feeder per machine.
- **Classification channel** — where pieces are imaged/classified. Has a large
  **classification dome** (aka "classification cap") that is ~the full print bed.
  Lighting parts here are **white** (diffusion).
- **Interface** — modular connector between feeder and the distribution frame.
  Holds bracket + spacer pairs (6 of each).
- **Distribution frame** — the big hex frame (6 sections) pieces drop through.
  One frame **per layer**. crossbeam ×6, 90° bracket ×12 per frame.
- **Chute** — central column; **chute core** and everything in the chute section
  are **per layer** (one chute per distribution layer).
- **Bins** — circle of bins per layer. Third-size bin = **18 per layer**.
- **Bottom lazy Susan** — at the very bottom; connects the chute to the external
  aluminium extrusion and lets it rotate.

## Scaling — READ THIS CAREFULLY

A machine = 1 feeder + 1 classification channel + 1 interface +
1 lazy Susan + **N layers** (each layer includes a distribution frame, a chute,
funnels, and bins).

**Per LAYER, not per machine** (these scale with the layer count):
- **Distribution frame** — there is ONE distribution frame **per layer**. Never
  describe it as "per machine." (The interface also contains some of these same
  frame parts inside it — that's the interface's own bracket/spacer set.)
- **Chute** — one chute **per layer** (chute core, funnel brackets, door module,
  bearing holders, servo adapter/bracket, chute door, bearing covers, and the
  layer connectors all scale with the layer count).
- **Bins** — each layer is *a layer of bins*. The third-size bin = **18 per
  layer**. Bins are **optional**.
- **Bin retainers** — per layer, **optional**. If you don't print bins, you
  don't need retainers.
- **Funnels** — 1 per layer.

So with N layers you get N distribution frames, N chutes, N×18 bins (if bins are
made), N funnels, etc. Everything else (feeder, classification channel,
interface, lazy Susan) is once per machine.

## Parts designed to bed-max

Many parts are intentionally near the full print-bed size (classification dome,
bulk bucket, etc.). That's why the CLI choked on the real 256mm bed — we slice on
a faked large bed (grams are bed-independent). See README.

## Colors

Color is set by **role** (user picks) unless a part *must* be a specific color.
Roles + defaults:
- **frame** → black
- **feeder** (C-channel system) → black
- **chute core** → white
- **funnel** → gray (light-bluish-gray)

Fixed/expected colors (NOT changed by the pickers):
- **Stator** ×4 = 1 gray + 3 black
- **Rotor (faceted)** ×3 = 2 white + 1 gray
- **Light post cap** ×2 (on C-channels 2 & 3) = white
- **Classification dome** = white (lighting)
- **Lazy-Susan "mount to chute"** = white (the rest of the lazy Susan = frame color)

## C-channel parts (4 C-channels)

- **Stator** — 4 total (1 gray, 3 black).
- **Rotor (faceted)** — 3 total (2 white, 1 gray).
- **C-channel leg** — 9 total.
- **Output gear (130 teeth)** — 1 per C-channel → 4 total. Feeder color.
- **NEMA bracket** — 1 per C-channel → 4 total. Feeder color. (All NEMA brackets
  are the same across C-channels; file is "Nema Bracket Bulk Section" — meaning
  of "bulk section" unknown, treat as the standard NEMA bracket.)
- **Light post cap** — 2 total (C-channels 2 & 3), white.
- **Bulk cap** — 1, sits on top of the first C-channel. Color not critical →
  default black (feeder role). (Distinct from the "bulk bucket" — a separate
  bed-max optional part, not yet provided.)

## Open / unconfirmed (verify with Spencer)

- Classification dome quantity (assumed 1).
- Bin retainer quantity per layer (assumed 1, optional).
- Lazy-Susan part quantities (assumed 1 each; washer may be several).
- `ribbon_cable_bracket / cage_bracket_ribbon.stl` — in inbox, unclassified.
- Interface top/bottom split — currently one "interface" section.

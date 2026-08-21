# Unified Parts System — Design

Status: draft for review (Spencer + Abrianbaker)
Date: 2026-07-18
Scope: consolidating the parts calculator, the Sorter V2 docs, and the
Sorter V2 BOM Google Sheet into one source of truth for parts, assemblies,
revisions, and machine releases. Everything described here is intended to
end up living in the sorter-v2 repo.

---

## 1. Purpose

Today the truth about "what is a Sorter V2 made of" is split across three
places that don't reference each other reliably:

| Source | What it uniquely owns today |
|---|---|
| **Parts calculator** (this repo) | 84 printed parts with *real sliced* weights/times, per-section quantities, color roles, layer scaling, variant groups, per-part version history tied to git commits and OnShape versions. Plus 3 laser-cut parts and 9 framing pieces in separate hardcoded models. |
| **Docs** (`sorter-v2-03/docs`) | Assembly knowledge. Has its own small parts catalog (`_data/parts.yml`) whose ids deliberately mirror this repo, a `parts_needed` frontmatter mechanism (adopted on one page), and free-form `applies_to` version strings. |
| **BOM Google Sheet** | All COTS/purchased data: vendor links, prices, pack quantities, "as of" dates, EU/CN alternate sources, the screw engineering table (size, length, head type, per-module counts, "In CAD?"), tools, stock material. |

The failure modes this design eliminates:

- COTS parts (screws, inserts, bearings, motors, cameras, PSU) exist only in
  a spreadsheet with hand-maintained totals that drift from CAD.
- Docs reference parts in prose; nothing checks that a page is still accurate
  after a part changes.
- There is no way to answer, about a physical part in someone's hand:
  *which revision is this, and is it compatible with the machine I'm building?*
- "Sorter 2.1 with a different feeder" has no representation: today it would
  mean forking a spreadsheet.

### The end state, concretely

1. **One registry** (data files in git) describing every part — printed,
   laser-cut, framing, and off-the-shelf — plus the assembly tree that
   composes them into a machine.
2. **One resolver** — `resolve(release, config, scope) → tally` — that every
   surface renders from:
   - The calculator becomes a *whole-machine* tally: select the whole machine
     or any subtree (one layer, just the chute, just the door module) and get
     everything — filament by color, screws by size, inserts, bearings,
     servos, cameras, extrusion cut lists — with buy links.
   - Each docs assembly page (e.g. chute-core) opens with a generated
     "you will need" block: `resolve(scope: chute-core)`. Never hand-listed,
     in sync by construction.
   - The Google Sheet is retired tab-by-tab (the Aluminum Extrusion tab is
     already stamped superseded and points at the calculator — that pattern
     continues), optionally kept alive as a one-way generated export.
3. **Answerable compatibility**: a builder reads the part number debossed on
   a printed part, searches it, and gets one of four states:
   **current / old-but-fits / incompatible / unknown** — plus what to do.

---

## 2. Core concepts

Five concepts, deliberately orthogonal. Most of the perceived complexity of
"part versions vs module versions vs machine variants" dissolves into these:

### 2.1 Part

A stable identity with a **slug** as the machine-readable key (`chute-core`,
`servo-bracket`) and a **part number** (`CHT-010`) as the human/physical
identifier. The slug is the key everywhere in data (it already is — in this
repo, in docs `parts.yml`, in filenames). The part number is a *field*, and
it is what gets physically debossed on printed parts. Registry enforces the
mapping 1:1. Parts never get renumbered or re-slugged.

Every part has a `kind`: `printed | lasercut | framing | cots`.
A camera and an M3 nut are parts exactly like a printed bracket is — they
just carry a `sourcing` block instead of an STL.

### 2.2 Revision (time, per part)

Two tiers:

- **Iterations** — every exported/sliced change, recorded in the part's
  `versions[]` with date, commit, OnShape version. High churn, no ceremony.
  This already exists (e.g. `interface-upper-fixed-section` v1 → v2,
  "Reshaped: now 35mm tall, rib attachments", each with a commit hash).
- **Released revisions** — an iteration published after a machine release
  exists, minted with a **letter** (A, B, …). The letter is debossed on the
  part. Initial-release geometry carries *no* letter (so an unlettered mark
  means "as released in 2.0" — that's information, not absence of it).

Each released revision carries one bit of judgment:

- `breaking: false` — old part still fits and functions; owners are not
  forced to reprint. (May still carry a note like "old revision can crack
  under X; reprint if that applies to you.")
- `breaking: true` — not interchangeable; old part does not work in builds
  that expect this revision or later.

Breaking revisions partition a part's history into **compatibility
generations**. Compatibility is then *computed*, never hand-maintained:

> A revision is compatible with a machine release iff the part is in that
> release's BOM and the revision is in the same generation as the revision
> the release pins.

Fuzzy cases must resolve to either (a) a boolean plus a human-readable note,
or (b) a config condition on the usage line (§2.5). "Compatible, sort of,
sometimes" is deliberately unrepresentable — that's what keeps the
builder-facing answer computable.

### 2.3 Machine release (time, whole machine)

A named cut: `2.0`, `2.1`. Stored as a tiny list (`releases.json`: id, date,
notes). Cutting a release emits a **lockfile** — the fully resolved BOM with
every part pinned to an exact revision. Lockfiles are immutable historical
records; they are what a builder builds against, what release notes are
diffed from (`resolve(current) − lockfile(2.0)` = "changes since 2.0"), and
what powers a "show me 2.0 exactly as shipped" view with per-revision STL
downloads.

Nothing in the versioning apparatus exists before the first release is cut.
We are actively building 2.0 right now; every part change until the 2.0
lockfile exists is pre-release iteration — no letters, no breaking flags, no
effectivity. **The whole system initializes empty by rule, not by judgment.**

### 2.4 Configuration (space, per machine instance)

Parameters a builder chooses: the layer list (`['third','third','half']`),
bin sizes per layer, funnel variant, optional modules. Already modeled well
in the calculator (per-section scaling, `variant_group`, `layer_scope`).
A concrete machine is **(release, configuration)**. Variants are named
preset configurations — *not* separate part trees.

### 2.5 Effectivity (membership over time/options)

Every BOM line (assembly → child, qty) can carry:

- `since` / `until` — machine-release range. Absent = always.
- `option` — a config condition (e.g. `feeder: mk2`).

This is how "2.1 has a completely different feeder while 90% of the machine
is shared" costs almost nothing: old feeder lines get `until: "2.0"`, new
feeder lines get `since: "2.1"`, the shared 90% is untouched.

**Decision rule for the feeder scenario** (release vs option): *will
old-feeder builds still be supported/published after the new one ships?*
- No, superseded → it's a release boundary (`since`/`until`).
- Yes, both buildable → it's a module option (`option: {feeder: classic}`).

The mechanism supports both, so the choice can be made per-change, forever.
No first-class "machine variant" forks — 90%-shared forks rot; conditions on
shared lines don't.

---

## 3. Composition: the assembly tree

### 3.1 Two attachment mechanisms

**`requires` — hardware committed to a single physical part.** Heat-set
inserts pressed into a bracket, a bearing seated in a bore, a press-fit
magnet. Rides the part definition; quantity scales automatically with part
count everywhere the part is used. (The docs repo independently invented
this as `heat_inserts:` on parts — this generalizes it.) A revision may
override `requires` (rev B moves to bigger inserts → recorded on the
revision, covered by the normal compatibility story).

**`lines` — assemblies as real BOM nodes.** An assembly (today just an
`{id, name, description}` label in this repo) optionally gains lines
referencing parts *or other assemblies* (recursive). Screws that join parts
belong to the joint — i.e. to the assembly — not to either part. So does a
camera dropped into an arm, a servo screwed into a bracket, a PCB.

**Placement rule, stated once:**

> Committed to a single physical part regardless of context (pressed,
> seated, glued) → part `requires`.
> Joins multiple parts, or is a component *of* a grouping (camera, PCB,
> servo) → assembly `line`.

### 3.2 Nesting, and why this isn't reinventing CAD

The tree is recursive because the machine genuinely nests:

```
machine
└─ layer                  ×N from config
   ├─ layer-frame         printed brackets + extrusion pieces + screws
   ├─ chute
   │  ├─ chute-core       (part — requires: heat inserts)
   │  ├─ door-module      printed parts + MG995 servo + screws + nuts
   │  ├─ layer-connectors …
   │  └─ pcb …
   └─ bin                 variant chosen per layer
├─ interface / top …
└─ feeder
   ├─ c-channel …
   └─ classification-chamber …
```

The OnShape assembly tree and this tree are related but deliberately **not
the same tree**. CAD is organized for modeling convenience (mirrors,
patterns, in-context edits) and answers *where does it go*. This tree is
organized for building and buying and answers *what do I need, in what
bundles*. Every real manufacturer maintains both (CAD + PLM); forcing them
to mirror each other is a known trap.

**Node guardrail** — the discipline that keeps the tree ~3 levels and honest:

> An assembly node must be a **unit of work or a unit of kitting** —
> something you'd assemble on the bench and set aside, hand someone as a
> labeled kit, or write a docs page about. Otherwise it's not a node; it's
> just parts in the parent.

Depth is per-branch and optional. The chute earns sub-structure; a lone
external bracket stays flat forever. Both coexist in the same resolve.

Strong evidence the tree is natural rather than invented: **the docs nav
already drafted it.** `distribution/chute/{chute-core, door-module,
mg995-servo, funnel, pcb, layer-connectors}` is a build-ordered hierarchy
someone already thought through. First-draft transcription, not design.

### 3.3 The resolver

The single engine everything renders from (~50–80 lines):

```
resolve(release, config, scope) → tally
```

- `release` — pins effectivity ranges; picks "latest revision in the pinned
  generation" per part (so a non-breaking improvement reaches existing
  releases automatically, without touching their lockfiles).
- `config` — layer list, bin/funnel choices, options; drives quantity
  expressions and `layer_scope`.
- `scope` — any set of tree nodes. Whole machine, one layer, `chute`,
  `door-module`. Defaults to the whole machine.

Walk the selected subtrees recursively (cycle check), multiply quantities
down, sum `requires` at the leaves, group the result by `kind`:

- printed → grams by resolved color, spool math, print time, plate downloads
- cots → shopping list with sourcing links, pack-quantity math
- framing → cut list fed to the existing bin-packing cut planner
- lasercut → sheet list with DXFs

The calculator today is exactly this resolver restricted to
`kind: printed` with scope = flat section checkboxes. The UI change is:
section checkboxes → tree selector; tally grows non-printed groups.

---

## 4. Part numbering & physical marking

Adopting Abrianbaker's proposal (2026-07-05) with adjustments agreed below.
Abrianbaker owns: the code list, PN assignment upkeep, the OnShape
FeatureScript ("Part ID Mark") and Fusion add-in, and registry maintenance.

### 4.1 The standard (from the proposal, adopted as-is)

- Format `PPP-NNN`, e.g. `FDR-010`, `CHT-010`. Numbers by 10s within a
  family; released numbers are never reused or renumbered.
- Revision suffix only after a released geometry change: `CHT-010-A`.
  Initial released parts carry no letter.
- STL filenames lead with the PN: `CHT-010_Chute_Core.stl`,
  `CHT-010-A_Chute_Core.stl`.
- Physical mark: debossed, 0.4mm deep, 3.0mm nominal text (2.4–3.2mm
  auto-scale), Allerta Stencil, lower-left of a safe non-functional flat
  face; avoid bearing seats, bosses, sliding faces, thin walls. Compact form
  `P-NNN` when space demands. Applied via the Part ID Mark FeatureScript.
- Purchased-part type codes for grouping COTS in the registry:
  SCR, NUT, HSI, WSH, BRG, MOT, SRV, FAN, CAM, PCB, CON, SNS, PSU, SBC,
  CBL, ELC, DRV, STD.

### 4.2 Adjustments (agreed direction)

1. **Slug stays the data key; PN is a field.** Rekeying two repos to
   `CHT-010` is churn with no gain. PN is what humans read and deboss; slug
   is what data joins on. 1:1 enforced by the registry.
2. **Section codes are mnemonic namespaces, not data.** BOM membership lives
   in the tree, never inferred from the `FDR-` prefix (the stator serves
   both the feeder and the classification channel; its PN prefix is just
   "where a builder first meets it").
3. **`breaking` bit added to revision rules** (§2.2). The proposal's "bump
   when geometry changes in a way that matters" needs the
   interchangeable-or-not distinction to make compatibility computable.
4. **The registry is data in git; the website renders it.** The proposal's
   "registry lives on parts-calculator.basically.website" is right about the
   *lookup*, but the source of truth is the manifest, versioned with
   everything else.

### 4.3 Marking/registry lockstep

The letter is baked into the STL geometry by the FeatureScript — the website
just serves the file. So minting a letter is **one act with two halves**:
bump the revision in the registry *and* the revision dropdown in the
FeatureScript, then re-export. This pairing is an explicit release-checklist
item (and squarely inside Abrianbaker's ownership). Failure is soft — a
missed mark means the physical part reads one revision old, and the lookup
still lands somewhere sane ("old but compatible") — but the checklist keeps
it rare.

### 4.4 Open decisions to settle (small, permanent — decide deliberately)

1. **Codes for sections the proposal doesn't cover.** Actual sections here:
   `feeder, classification-channel, interface, chute, funnel, layer
   (distribution frame), lazy-susan, bins, electronics`. Proposal codes:
   FDR, IFC, DST, CHT, FUN, BIN, JIG, SPX. Unmapped:
   - `classification-channel` — own code (CCH?) or fold into FDR (it sits
     atop the feeder)?
   - `lazy-susan` — own code (LSN?) or DST (it lives in the distribution
     frame)?
   - `electronics` printed parts (3 mounts/boxes) — ELC or SPX?
2. **Home section for the 8 multi-section parts** (PN prefix only; BOM
   membership unaffected): `stator`, `output-gear`, `nema-bracket`
   (feeder + classification-channel); `ext-bracket-left`,
   `ext-bracket-bottom-vertical`, `ext-bracket-cover` (layer + interface);
   `layer-connector-1`, `layer-connector-2` (chute + interface).
   Tiebreak suggestion: where a builder first encounters it.
3. **Numbering order within each family.** Arbitrary but frozen forever.
   Rough assembly order is slightly nicer for the future manual; current
   manifest order is acceptable. Largest family (interface, ~21 printed
   parts) lands at IFC-210 — comfortable in three digits at 10-spacing.

---

## 5. Schema

Extending `slicer/parts.json` (which stays the authored manifest; the build
still generates the app's data from it). **Schema rule: a field may only be
added if its absence means something sensible for every existing part.**
That rule is why all 84 current parts are valid on day one with zero edits.

### 5.1 Printed part (existing fields + new, annotated)

```jsonc
{
  "id": "chute-core",                  // existing — THE key, never changes
  "part_number": "CHT-010",            // NEW — human/physical id, 1:1 with slug
  "kind": "printed",                   // NEW — printed|lasercut|framing|cots
  "name": "Chute core",
  "description": "The chute core. 1 per machine.",
  "internal_notes": "…",
  "onshape_doc": "https://cad.onshape.com/documents/…",  // existing — LIVE
  // document link (where to go edit). Distinct from the per-revision
  // onshape_version pins below; both are shown on the part page.

  // existing quantity/section model — unchanged; over time superseded by
  // assembly lines (§5.3) but both are honored during migration
  "quantities": { "chute": 1 },
  "assembly": null,
  "layer_scope": "all",                // existing: all|non-bottom|bottom-only
  "variant_group": null,
  "optional": false,

  "color": { "role": "chute-core" },   // existing color system — unchanged
  "stl": "parts/chute/chute-core.stl",
  "support": false,

  // NEW — hardware committed to this physical part (§3.1)
  "requires": [
    { "part": "hsi-m3-short", "qty": 2 }
  ],

  // existing versions[], extended per entry with the release-era fields
  "versions": [
    {
      "version": "1", "date": "2026-06-27",
      "message": "Initial version.", "commit": "be3f4cd"
      // pre-release iteration: no letter, no breaking, nothing else needed
    },
    {
      "version": "2", "date": "2026-09-14",
      "message": "Reinforced rib. Unlettered revision can crack when the door slams under load.",
      "commit": "abc1234",
      // immutable link to the exported OnShape *version* (/v/ URL) — every
      // revision pins the exact CAD state it was exported from, forever
      "onshape_version": "https://cad.onshape.com/documents/…/v/…",
      "letter": "A",                   // NEW — minted because 2.0 is released
      "breaking": false,               // NEW — old part still fits; optional reprint
      "stl_hash": "sha256:9f2c…"       // NEW — content address in the bucket (§7)
    }
  ]
}
```

### 5.2 COTS part

```jsonc
{
  "id": "mg995-servo",
  "part_number": "SRV-010",
  "kind": "cots",
  "name": "MG995 servo",
  "attributes": [                       // existing attributes mechanism
    { "label": "Type", "value": "Standard size, metal gear" }
  ],
  "sourcing": {                         // NEW — subsumes the sheet's columns
    "vendors": [
      { "region": "US", "url": "https://…", "price": 17.98,
        "pack_qty": 4, "as_of": "2026-04-16" },
      { "region": "CN", "url": "https://aliexpress…", "price": 3.10,
        "pack_qty": 1, "as_of": "2026-04-30", "note": "unconfirmed" }
    ]
  }
}
```

A screw is the same shape, with the sheet's engineering table as attributes:

```jsonc
{
  "id": "scr-m5-18-bhcs",
  "part_number": "SCR-030",
  "kind": "cots",
  "name": "M5×18 button head",
  "attributes": [
    { "label": "Head", "value": "Button" },
    { "label": "Ideal length", "value": "18mm (mid-thread 16.0, max 19.1)" },
    { "label": "Mates with", "value": "Spring-loaded roll-in T-nut" }
  ],
  "sourcing": { "vendors": [ /* … */ ] }
}
```

Where the sheet had a hand-typed quantity column per module, quantity is now
**derived** — the sum of every `requires` and assembly line that references
the screw, times resolved part/assembly counts. The screws tab's totals stop
being maintainable-wrong.

### 5.3 Assembly node (recursive lines + effectivity)

```jsonc
{
  "id": "door-module",
  "name": "Chute door module",
  "description": "Flap, servo, bearings — assembled on the bench as a unit.",
  "lines": [
    { "part": "chute-door",       "qty": 1 },
    { "part": "servo-adapter",    "qty": 1 },
    { "part": "mg995-servo",      "qty": 1 },
    { "part": "brg-6704-2rs",     "qty": 2 },
    { "part": "scr-m3-8-bhcs",    "qty": 6 },
    { "part": "nut-m3",           "qty": 6 }
  ]
}
```

```jsonc
{
  "id": "chute",
  "name": "Chute",
  "lines": [
    { "part": "chute-core", "qty": 1 },
    { "assembly": "door-module", "qty": 1 },
    { "assembly": "layer-connectors", "qty": 1 },

    // effectivity examples (only appear when 2.1 actually diverges):
    { "part": "old-funnel-adapter", "qty": 1, "until": "2.0" },
    { "part": "new-funnel-adapter", "qty": 1, "since": "2.1" },

    // option example (if old and new feeders remain co-supported):
    { "assembly": "feeder-classic", "qty": 1, "option": { "feeder": "classic" } }
  ]
}
```

### 5.4 Releases and lockfiles

```jsonc
// releases.json
[ { "id": "2.0", "date": "2026-08-01", "notes": "Initial public release." } ]
```

```jsonc
// releases/2.0.lock.json — emitted by the resolver at cut time, immutable
{
  "release": "2.0",
  "resolved": {
    "chute-core":  { "revision": null,  "stl_hash": "sha256:71aa…" },  // null = unlettered initial
    "chute-door":  { "revision": null,  "stl_hash": "sha256:03bd…" },
    "mg995-servo": { "revision": null }
  }
}
```

### 5.5 Laser-cut and framing parts

Folded from `lasercut.ts` / `framing.ts` into the manifest with
`kind: "lasercut"` (thickness/dxf/preview fields) and `kind: "framing"`
(length, cut source). The cut-planner and DXF preview tooling read from the
manifest instead of hardcoded arrays. Framing's `qtyFor(n)` functions become
quantity expressions on lines like everything else.

---

## 6. Workflows (the model exercised end-to-end)

### W1 — Designer iterates a part (weekly, pre- and post-release)

Edit in OnShape → export → slice → append an iteration to `versions[]`
(date, commit, OnShape version). No letters, no judgment. Identical to
today's flow.

### W2 — Minting a released revision (the fringe-crack example)

Post-2.0, `chute-core` gets a reinforced rib because the original can crack
in a fringe circumstance:

1. Edit geometry **and** bump the Part ID Mark revision dropdown to A
   (one act, two halves — §4.3). Export, slice.
2. Registry entry: `letter: "A"`, `breaking: false`, message
   *"Reinforced rib; unlettered revision can crack if X."*
3. **2.0 and its lockfile are untouched.** Because A is non-breaking (same
   generation), "latest revision in the pinned generation" makes A the
   served revision for 2.0 automatically.

What people see:
- **New builder**: downloads serve A; the print comes out marked
  `CHT-010-A`; they never notice anything happened.
- **Existing 2.0 owner**: their part reads `CHT-010`, no letter — which now
  *means* "initial 2.0 release." Lookup answers: **old but compatible** —
  "superseded by A; reprint if the fringe case applies to you."
- **Docs**: staleness linter flags pages referencing chute-core whose
  `last_verified` predates A; author re-verifies, bumps date.
- **Release feed**: `resolve(2.0) − lockfile(2.0)` mechanically yields
  "CHT-010 → A (non-breaking): reinforced rib."
- **Discord support**: "my chute door thing cracked" → "check the deboss —
  no letter? Known issue, print A."

Had the change been breaking instead: `breaking: true`, and A waits for the
next release (or a 2.0.1 lockfile is cut that pins it). If it only breaks
for some configurations, it's an `option` condition on the line instead.

### W3 — Cutting 2.1 with a new feeder

Create release `2.1`. Old feeder subtree lines get `until: "2.0"`, new
feeder assembly `since: "2.1"`. The ~90% shared machine: zero edits. Emit
`releases/2.1.lock.json`. Release notes are the lockfile diff. If both
feeders stay supported, use `option: {feeder: …}` instead and 2.1 simply
changes the default — §2.5's decision rule.

### W4 — Builder with a bin of mystery parts

Read the deboss → search on the calculator → part page shows: name, where
it lives in the tree, revision history (lettered revisions prominent —
date, message, compat status, per-revision STL download and render, git
commit link, and the immutable OnShape version link;
pre-release iteration log tucked behind a "development history" disclosure),
and the four-state verdict against the release they're building. Unmarked
part = predates marking adoption → "unknown; at least as old as [marking
adoption date]" plus per-revision render images for visual identification.
This state never fully disappears for pre-marking prints — which is the
argument for adopting marking early, before the wild population grows.

### W5 — Docs author writes the chute-core assembly page

Frontmatter: `parts_needed: { assembly: chute-core }` (or a node list).
The build renders the "you will need" block from
`resolve(scope: chute-core)` — printed parts with renders, screws with
sizes, inserts, the servo — grouped by kind with quantities. The linter
validates every referenced id against the registry and flags stale
`last_verified` against revision dates. `applies_to` becomes a real range
against `releases.json` (e.g. `">=2.0 <3"`) instead of free-form strings.

### W6 — Builder tallies a partial build

Calculator scope selector: tick `layer` ×2 and `feeder`, get the combined
tally — filament by color and spool math, a shopping list with vendor links
and pack-quantity math, extrusion cut plan, laser sheets. Print-and-buy for
exactly the subset being built. Per-assembly "kit view" is scope = one node.

---

## 7. STL storage (out of git, content-addressed)

STLs (and renders/3MFs) do not belong in git history, and Git LFS conflicts
with the Vercel deploy path. Instead:

- **GH Action on push**: hash each artifact (`sha256`), upload to a bucket
  (Cloudflare R2 — no egress fees) at `stl/<hash>.stl` **only if absent**.
  Content addressing gives dedupe and immutability for free.
- The manifest/lockfiles store `stl_hash`; the site links
  `cdn…/stl/<hash>.stl`. Vercel builds only read the small generated JSON.
- Because revisions pin hashes, **every historical revision stays
  downloadable forever** with zero redundancy and no archive to maintain —
  old versions are just links that never break. This is what powers the
  per-revision downloads (W4) and the "2.0 exactly as shipped" view.

**Caching invariant.** Objects are served `public, max-age=31536000,
immutable`. That is safe *only* because the URL contains the content hash:
the bytes at a given URL can never change, so a cached copy can never be
stale. Two rules preserve this:

1. **Never serve a stable-name URL** (e.g. `/stl/chute-core.stl`, whose
   content changes across revisions) with long-lived cache headers. Every
   public artifact URL is hash-addressed. A friendly-name alias, if ever
   added, gets a short TTL.
2. **Never use presigned URLs** for public artifacts — they expire. These
   are public-read objects at permanent keys.

Origin and CDN hostnames both serve the objects permanently, so switching
between them is not a breaking change either.

The one real dependency is bucket availability — which is why the masters
stay committed in git as the archival copy.

**Dual storage (as built, 2026-08-20).** Plain git holds the canonical
masters (`slicer/parts/**`, not LFS — see `.gitattributes` for why LFS is
banned); the bucket is the serving layer. The site never reads repo binaries
— every download URL in the generated JSON is a bucket URL, superseded
version geometry is pinned by `stl_hash`, and the old `static/stl/` serving
copies and the committed `all-parts.zip` are gone. The masters leave git too
once uploads stop requiring bucket credentials (the asset-service plan);
until then, committing the STL in the PR is what lets any agent author a
part.

---

## 8. What we are deliberately NOT doing

- **No database, no Airtable, no PLM tool.** At 100–300 parts, git + JSON +
  a resolver wins: reviewable diffs, history tied to commits, free hosting.
- **No versioned assemblies.** Assemblies are stable identities; their
  *lines* carry effectivity, and lockfiles snapshot the resolved whole.
  Assembly-level version numbers add tree-maintenance burden and buy nothing.
- **No first-class machine-variant forks.** Releases + options on shared
  lines. Forked 90%-shared trees rot.
- **No per-version docs rendering.** Track and lint staleness; don't fork
  content. (A rabbit hole with no bottom.)
- **No mirroring the CAD tree.** §3.2.
- **No fuzzy compatibility data.** Boolean + note, or a config condition.
  Nothing else. §2.2.
- **No renumbering, ever.** Released PNs and slugs are permanent. §4.1.

---

## 9. Migration plan

Each step independently shippable, in dependency order. 1–3 are the core
("rip through in a day-ish" each); after them the unified tally works end to
end on printed parts and everything else is enrichment.

1. **Schema v2** — add `kind`, `part_number`, `requires`, `sourcing`,
   recursive assembly `lines` to the manifest; fold in `lasercut.ts` and
   `framing.ts`. All 84 printed parts valid with zero edits (absent-default
   rule, §5).
2. **Resolver** — recursion, cycle check, config scaling, scope, effectivity,
   generation-aware revision pick. The single engine (§3.3).
3. **Tree transcription** — script a first draft from the existing
   `quantities` maps + the docs nav hierarchy; one human review pass
   applying the bench/kit/docs-page node rule.
4. **PN assignment** — script proposed `PPP-NNN` for all 84 in manifest
   order; settle §4.4's three decisions with Abrianbaker; review once;
   commit. Begin debossing via the FeatureScript as parts are next touched.
5. **COTS import** — the sheet's Screws + both Parts-To-Buy tabs become
   `kind: cots` parts with sourcing blocks, placed as `requires` or lines.
   The long pole (data entry + placement judgment); do it
   assembly-by-assembly — the tally is useful before it's complete.
6. **Calculator UI** — tree scope selector; tally grows COTS/framing/laser
   groups; PN search; part pages with revision history (old revisions behind
   a disclosure).
7. **Releases** — `releases.json`; cut **2.0** + lockfile at declaration.
   Letters, `breaking`, and effectivity begin existing at that moment.
8. **Docs wiring** — registry artifact consumed by the docs build
   (generate `_data/parts.yml` or fetch published JSON); assembly-scoped
   `parts_needed`; extend `validate_frontmatter.py` into the id +
   staleness linter; structured `applies_to`.
9. **STL bucket** — §7. Done: artifacts are content-addressed in the Space
   and the site links to them.

   **Ordering constraint — do not migrate git history to LFS before step 1.**
   Historical part revisions are not stored; they are *reconstructed* from
   git history (`archive_versions()` runs `git show <commit>~1:<path>` to
   recover pre-change geometry). After an LFS migration `git show` returns
   pointer text, the `is_lfs_pointer()` guard fires, and the revision
   silently falls back to the *current* geometry — wrong data, no error.
   Once each revision pins its own `stl_hash` (step 1), the bucket is
   authoritative and git history stops being load-bearing; the migration is
   then safe. If moving sooner, run `filament.py --force` first so every
   revision still discoverable in history gets archived to the bucket.
10. **Sheet retirement** — stamp each tab superseded with a link as its
    domain migrates (extrusion-tab pattern). Optionally add a one-way
    lockfile→sheet export for spreadsheet lovers; never authoritative again.

---

## Appendix: current-state facts this design was built against

- Calculator: 84 printed parts in `slicer/parts.json` (all currently valid
  against schema v2 with zero edits); 3 laser parts; 9 framing pieces;
  14 assembly labels; 2 variant groups (funnel, bin); 9 sections; layer
  config `['third','third','half']`; 81 parts at internal version 1, 3 at
  version 2; 5 parts with explicit `versions[]` histories; 2 with OnShape
  version links.
- Docs: ~60 pages, Jekyll; `_data/parts.yml` ids deliberately mirror this
  repo ("so the two merge cleanly later" — its own header); `parts_needed`
  used on exactly one page (bottom-interface); frontmatter enforced by
  `scripts/validate_frontmatter.py`; `applies_to` free-form.
- Sheet: 10 tabs; Aluminum Extrusion already stamped superseded → the
  calculator; Screws tab tracks "In CAD?"/"Correct in CAD?" columns —
  exactly the drift problem derived quantities eliminate.
- Part numbering proposal: Abrianbaker, 2026-07-05, with working OnShape
  FeatureScript ("Part ID Mark") and Fusion add-in in progress.

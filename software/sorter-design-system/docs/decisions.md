# Decisions

What was decided, and when. When a rule changes, the rule's own file changes
and a dated entry goes here; the history is git.

## 2026-09-29

- **One place.** The design system is `software/sorter-design-system`: a
  site that shows every rule working, and the components the Sorter UI,
  Hive and the SorterOS pages copy. The copies of the rules that each site
  carried (in AGENTS.md files, an in-app `/styleguide` route in each app, a
  styleguide page on the docs site) were removed and point here.
- **Planes, not outlines.** A screen is canvas, surfaces, wells and the
  raised plane, told apart by fill. The old UI separated almost everything
  with 1px outlines on one background color, so boxes nested five deep and
  their borders doubled.
- **Never two lines together.** Every line has one owner.
- **No shadows at all**, not even under what floats: its fill and one line
  separate it.
- **One loading indicator**, the Spinner, carried over from the Sorter UI.
- **14px is the smallest readable text**; the 12px body and 11px labels of
  the old styleguide page are gone.
- **Warning is LEGO yellow, `#FFD500`**, with `on-warning` (a dark ink) for
  text on it. The apps' `#F2A900` changes when they adopt the system.
- **Four button variants.** The Sorter UI's `success` variant and the old
  "brand confirm" button (a fixed green whatever the primary) are gone.
- **Our own Select.** The browser's dropdown looks different on every system
  and does not match the page; the system's list does.
- **The side nav sits on the surface plane**, a full-height column beside the
  content, not on the page's background.
- **An app screen is exactly the window** from `lg` up; lists scroll inside
  their panels, and the page never does.
- **One size scale.** Control heights, badges, switches, rows, the top bar and
  the current page's mark come from one set of tokens, so nothing reads
  cramped next to its neighbor. The current page's mark is 3px and as wide as
  its link.
- **Channel pages show their camera**, with the stepper's controls beside it
  as one jog control.
- **The wordmark is "Sorter"** in sentence case, not capitals.
- **Round shapes**: a status dot, a radio, and a person's avatar on Hive.
  Everything else follows the corner tokens, including Hive's badges.

### The look, chosen from options side by side

Each was chosen on the site from five to seven options drawn the same way
next to each other, and each winner is now the only value in `app.css`.

- **Typeface: Geist, with Geist Mono.** Chosen over IBM Plex Sans (the apps'
  typeface until now), Inter, Instrument Sans, Figtree, Public Sans and
  Schibsted Grotesk.
- **Labels in sentence case, and numbers in the typeface's tabular
  figures.** Nothing is in capitals, and numbers are not in the mono.
- **Corners of 1px**, from square, 1px, 2px, 4px, 6px, 8px and pill buttons:
  everything reads as square with its edge just softened. A radio, a status
  dot and an avatar are round.
- **Tinted buttons.** The primary is its own tint with its ink, the secondary
  a neutral tint, danger its tint; nothing is a solid block of color. Chosen
  over a solid primary with an outlined or a soft secondary, an ink primary,
  and outlines.
- **Compact sizes**: 36px controls, 30px in a dense row, over a roomier 40px
  scale.

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
- **Light or dark is a setting, never a control in the top bar**: Settings >
  General on a machine, the account's settings on Hive, as on the real
  Sorter. The site's own mode and color controls moved to the foot of its
  side nav, so nothing here shows a theme switch in a top bar.
- **The top bar folds on a narrow screen.** Its pages become one menu named
  for the current page, at a width each app sets; before, the links scrolled
  sideways and cut "Dashboard" off at 390px.
- **A setting changed from its default** takes the primary's tint and one
  "Reset to ..." button beside its name. It replaces the Sorter UI's amber
  row and icon: a changed value is a choice, not a warning.
- **A dialog that cannot be closed** while a restart, a reboot or a power
  down runs: no close button, Escape does nothing, and a status line with
  the Spinner says what is happening.
- **A card you open fills under the pointer**, like any state; it never
  lifts or casts a shadow. The whole card is a link, and the buttons in it
  still work.
- **The components render on the server too**, for Hive: ids from
  `$props.id()`, and no `window` or storage outside the browser.
- **A media tile hugs its picture; a layout never gives it a height.** The
  first version stretched a feed's box to the height the dashboard chose, so
  two feeds had black bars above and below and the third down both sides.
  Now the picture's box takes the feed's own shape (read from the loaded
  image or video, with `aspect` as its shape until then), `fill` is gone, and
  the dashboard sizes the group of three cameras to their pictures so they
  fill the window's height with no bar; the right column takes the rest of
  the width. Full screen is the one place a picture has bars.
- **A part's picture sits on the surface.** No grey well or box behind a
  part's image on the dashboard's recent pieces or anywhere a part is shown:
  it made every thumbnail a boxed, framed thing.
- **No padded tracks: they read as heavy borders.** With 1px corners and no
  shadows, a grey track with white segments in it looked like a thick grey
  border around the jog buttons and the Degrees / Time choice. A segmented
  control and the jog control are one control now: a single 1px
  `line-strong` outline, the segments divided by 1px lines with no gap and no
  padding, the chosen one filled with the primary's tint and its ink (chosen
  over a neutral fill because a chosen item is the primary's tint everywhere
  else). The `thumb` token is gone; `track` stays for the progress bar.
- **A page whose main thing is a camera uses the whole width.** A channel
  page was capped at 1152px like a page of forms, so on a wide screen the
  camera was small and half the window empty. It now takes the content width
  up to 1800px, the camera beside the stepper's panel from `xl` and above it
  below; pages of forms keep 1152px.
- **A button that opens a menu is three dots.** The top bar's machine menu
  showed a power icon, which read as a button that powers the machine off.
  It is `ellipsis` with a name; `power` and `power-off` are only for the
  items inside the menu, next to their words.

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

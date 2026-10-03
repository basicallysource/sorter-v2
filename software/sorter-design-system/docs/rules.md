# Rules

The ten rules, in the order and with the titles the site's Rules page uses.
When a screen looks off, it is almost always one of these. Each links to the
file that says more.

## 1. Planes, not outlines

A screen is built from four planes: the canvas (the page), surfaces (panels),
wells (sunk into a panel) and the raised plane (what floats). Each is told
apart from the one under it by its fill, never by an outline, and nothing
casts a shadow, not even what floats. Planes nest one way only: the canvas
holds panels, a panel holds rows, sections and wells, and a well holds
content. A panel never sits in a panel; when it seems to need one, it needs
a section (a heading, or a line between rows). See [surfaces.md](surfaces.md).

## 2. Two lines never meet

No double borders, anywhere. A double line appears where two parts both draw
the edge between them, so every line has one owner: the rows of a list own
the lines between them and none at the ends, a panel has no border, the top
bar owns the line under it, and controls in a row keep a gap. Choices that
belong together are one control: one outline and one line between the
segments, never a padded track. A divider runs the full width of its panel by
default; it is inset only where a full line would cut one group in two. The
ownership rules are in [surfaces.md](surfaces.md).

## 3. One loading indicator

Anything loading shows the Spinner, and nothing else spins: no
`animate-spin`, no spinning `Loader2` or refresh icon, no rotating ring. When
the shape of what is coming is known, a skeleton may hold its place; a
skeleton fades and never spins. See [loading.md](loading.md).

## 4. State is a fill

Hover and press lay a faint fill over whatever plane is under them, the
chosen item takes the primary's tint, and keyboard focus draws a 2px outline
in the primary. A field shows focus by drawing its own edge 2px in the
primary, over the field's line rather than outside it. No line gets thicker,
and no border appears, to show state.

## 5. Color carries meaning

Neutrals carry structure. The primary marks what someone acts on, where they
are, and focus. The status colors mean their status and nothing else: green
is running or done, yellow needs attention, red has failed or will destroy
something, blue is information. If the primary is the same color as a status,
the status still wins on its own component. No color decorates. See
[color.md](color.md).

## 6. Corners from the tokens

Every corner is one of the radius tokens: `rounded-panel`, `rounded-control`,
`rounded-item`, `rounded-button`, `rounded-button-inner`, `rounded-badge`,
`rounded-check` and `rounded-radio`. They are 1px, so everything reads as
square with its edge just softened. Nothing sets its own radius, so every
panel, field and button agrees. A radio and a status dot (`rounded-full`) are
round; so is a person's avatar on Hive.

## 7. Readable is 14px

Anything someone has to read is 14px (`text-sm`) or larger: settings, help,
messages, table cells, names, labels. 12px (`text-xs`) is only for what can
be skipped: a badge, a count, a bin code, a time. Nothing is smaller than
12px, and nothing is in capitals: labels are sentence case like every other
word. See [type.md](type.md).

## 8. Tokens, never raw colors

Markup names a token (`bg-surface`, `text-ink-muted`, `border-line`), never a
hex value and never Tailwind's own palette (`bg-white`, `text-gray-500`):
neither follows the mode. The exceptions are data that is a color (the LEGO
colors, a part's color), categorical colors drawn over a photo, and static
images such as favicons. In an arbitrary value, name the property itself:
`border-(--primary)`, `var(--line)`. See [color.md](color.md).

## 9. Lucide icons, beside words

Every icon is Lucide, imported one at a time from `@lucide/svelte/icons/`.
Never draw one: no hand-written SVG paths in a component. An icon sits beside
a word, or it is an icon button with a name. See [icons.md](icons.md).

## 10. Copy the component

Apps copy these components as they are, and a new look is made here first,
then copied again. So there is one Button, not one per screen. Components
take callback props (`onclose`, `onchange`), never `createEventDispatcher`.
See [engineering.md](engineering.md).

## What these settle

The copies of the rules that each site used to carry disagreed. This is what
holds now:

- **Text size.** 14px is the smallest readable size. The old rule of 12px
  body text and 11px labels is gone, and so is every 10px and 11px size.
- **Round shapes.** A status dot, a radio and a person's avatar on Hive are
  round. Everything else takes the corner tokens (1px); the old exceptions (a
  celebration check circle, pill chips drawn by hand, a rounded spinner) are
  gone.
- **Loading.** The Spinner only; the old example with a spinning `Loader2` is
  gone.
- **Notices.** One `Alert` in four tones, drawn from tokens; the old
  notification markup built from raw hex values is gone.
- **The primary.** On a machine the operator picks it from 64 LEGO colors;
  Hive is LEGO red and has no picker; the docs site is LEGO red.
- **Warning yellow.** LEGO yellow, `#FFD500`. The apps' tokens still say
  `#F2A900`, an amber, until they adopt the system.
- **Events.** Callback props, not `createEventDispatcher`.
- **Buttons.** Four variants: primary, secondary, ghost, danger. The old
  "success" button and the "brand confirm" button (a fixed green whatever the
  primary) are gone; a confirm is the primary.

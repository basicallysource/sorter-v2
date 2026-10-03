# Surfaces

A screen separates its parts with planes of different fill instead of
outlines. Lines are for dividing items and outlining controls, and every
line has one owner, so two never meet.

## The planes

| Plane   | Token        | What goes on it                                                                              |
| ------- | ------------ | -------------------------------------------------------------------------------------------- |
| Canvas  | `bg-canvas`  | The page: page titles, the gaps between panels                                               |
| Surface | `bg-surface` | A panel (`Panel`), the top bar, the side nav column                                          |
| Well    | `bg-well`    | Sunk into a panel: a chart, a preview, an empty list                                          |
| Raised  | `bg-raised`  | What floats: a popover, a menu, a select's list, a tooltip, a dialog                         |
| Media   | `bg-media`   | Behind a camera feed or a photo. Dark in both modes, so a picture never sits in a bright box |

A plane is told apart from the one under it by its fill alone. A panel has
no border and no shadow. Nothing in the system has a shadow: the raised plane
is the one thing with a line around it, and that line and its fill are
enough.

## Nesting goes one way

The canvas holds panels. A panel holds rows, sections and wells. A well holds
content, never another well. When a panel seems to need a panel inside it,
it needs a section instead: a heading, or a line between two groups of rows.
The old UI's worst screens were five bordered boxes deep; the most this
allows is canvas, surface, well.

A group's name inside a list (the pieces that have left the machine, under
the ones still in it), a section's name in a panel of settings and a table's
head are `label`s on the list's own plane, with the rows' line above and
below. None is a band of well: across a panel's full width a well is a shade
off the canvas, and reads as a gap in the panel with a word in it. A well is
a box inside a panel, with the panel's fill around it.

## Two kinds of line

Both are 1px. There is no thicker structural line; emphasis comes from fill
and color.

- `line` (`border-line`, `divide-line`) divides items on one plane: the rows
  of a list, the sections of a panel, a panel's footer from its body.
- `line-strong` (`border-line-strong`) outlines a control you type in, tick
  or choose from: a field, a select, a checkbox, a segmented control. The
  outline says "you can act here". Buttons are tints and have no outline.

A divider runs the full width of its panel by default: a row's padding is
inside the row, so `divide-y` on the rows draws edge to edge. Inset a divider
(to the text's edge) only where a full line would cut one group in two, such
as a short list inside a well.

The only lines thicker than 1px are state markers: the current page's or
tab's mark (`--indicator`, 3px) and the 2px focus outline.

## Who owns a line

- **A list or a table.** The rows own the lines between them. No line above
  the first row or below the last, and the panel around them has none.
  Tables use `.data-table`, whose head is a row of labels with the rows'
  line under it.
- **A panel.** Owns only the line above its footer. Its edges are its fill.
- **The top bar.** Owns the line under it. Nothing below it draws a line at
  its top, and a banner under it is a fill.
- **A tab bar.** Owns the line under it, and the current tab's mark sits on
  that line in place of it.
- **Controls in a row.** Keep a gap of at least 8px. Choices that belong
  together are one control: a single `line-strong` outline with one 1px
  line between the segments, no gap and no padding, the chosen one shown by
  a fill (a segmented control, the jog control). Never a padded track with
  loose segments in it: with 1px corners and no shadows it reads as a thick
  grey border around white boxes.
- **A grid of cells.** Stats in a row are a grid with `gap-px` on a
  `bg-line` background and a fill on each cell: the gaps are the lines, so
  there is never one at the edge.

If a layout change puts a line next to a border, remove one; never thin one.

## State

Hover lays `bg-hover` over whatever plane is under it, and press `bg-pressed`
(both translucent, so one token works on every plane). The chosen item in a
list or nav takes `bg-primary-soft` with `text-primary-ink`. Keyboard focus is
a 2px primary outline, 2px out; a field draws its own edge 2px primary instead.
A card you open (`Card`) and a setting changed from its default are fills
too: nothing lifts, casts a shadow or thickens its line to show a state.

## The raised plane

A popover, a menu, a select's list, a tooltip and a dialog are the raised
plane: `bg-raised` with a 1px `border-line`, and no shadow. They render in the
browser's top layer, so no ancestor's overflow clips them. A dialog alone
dims the page behind it (`bg-scrim`). See [overlays.md](overlays.md).

## Media

A camera feed or a photo sits on `bg-media` (`MediaTile`), and the tile is the
shape of its picture, so the backdrop is never seen as a bar. Where a picture
is shown whole in a box of another shape (a piece's crop in a grid of square
tiles, a thumbnail in a row), it has no backdrop at all: it sits on the fill
of the card or row it is in. What is drawn
over the picture (a "Live" badge, a chip) sits in a `dark` subtree, so it uses
the dark tokens whatever the page's mode ([color.md](color.md)).

A part's image is not media: it sits straight on the panel or the row it is
in, with no well and no backdrop behind it.

## Corners

Every plane's corners come from the radius tokens, all 1px: `rounded-panel`
for a panel or a dialog, `rounded-control` for a field, a well or a menu,
`rounded-item` for a row in a menu or a nav, `rounded-button` for a button.
What runs to a panel's edge (a table, a picture) is clipped to its corners.

# Components

Every component is one file in `src/lib/components/`, with a comment at its
top that says what it is for. An app copies the file unchanged
([engineering.md](engineering.md)). The site has a page for each group, and
the example app shows them together.

## Button

`Button.svelte`. Four variants, two sizes.

| Variant     | For                                                                           |
| ----------- | ----------------------------------------------------------------------------- |
| `primary`   | The one thing to do in a panel or a dialog                                    |
| `secondary` | Any other action                                                              |
| `ghost`     | The way out, and actions in a row of many (a camera's -1°, +1°, 180°)         |
| `danger`    | Deletes or stops something for good; only in the confirmation that asks first |

- Every variant is a tint with its own ink: the primary's tint for
  `primary`, a neutral one for `secondary`, the danger tint for `danger`.
  Nothing is a solid block of color. The `--btn-*` tokens in `app.css` hold
  the colors.
- `size`: `md` for a page or a dialog, `sm` in a dense row or a panel's
  header, `lg` (44px) for a touch screen's main action, such as the Wi-Fi
  setup page's Join.
- `icon` leads the label. With an icon and no label it is an icon button, and
  `label` is its name and its tooltip.
- `loading` swaps the icon for the Spinner and keeps the label, at full
  strength: the button is busy, not unavailable. `disabled` fades it.
- `href` makes it a link that looks like a button, for going somewhere
  rather than doing something.
- In a row, the way out comes first and the primary last. Buttons keep a gap
  of at least 8px.

## Fields

- **`Input`**: a text or number field. `unit` sits inside the field's edge
  after the value ("6 /min"); `end` puts a small control there instead (a
  Show button on a password). `invalid` draws the edge in danger. Numbers are
  right-aligned in tabular figures. `size="lg"` is 44px, for a touch screen.
  `bind:element` gives the `<input>` itself, to focus it from code, and every
  other attribute (`id`, `name`, `autocomplete`, `required`, `onkeydown`)
  goes on it; `class` goes on the field's edge.
- **`Select`**: one choice from a list, in our own list rather than the
  browser's ([overlays.md](overlays.md)). `label` names it when no `<label>`
  points at it. `class` goes on a wrapper, so `class="w-44"` sizes it. In a
  form, `name`, `required` and `autocomplete` go on a hidden native select
  that submits the value.
- **`Textarea`**: several lines. Every other attribute goes on the
  `<textarea>`.
- **`Field`**: a label over a control, and one sentence under it: help, or
  the error in its place, in danger ink. Give the control the same `id` as
  `for`. `info` explains a setting whose name cannot say it all, where a
  sentence under every field would crowd a dense row: an ⓘ beside the label
  opens it in a Popover.
- **`CopyField`**: something to copy, shown whole: a key, a token, a message
  with one in it. It is laid out like a `Field`, with no control for a
  `Field` to point at: `label` above, the text in a well with one Copy button
  at its edge, and `note`, one sentence, under it. The button says Copied for
  a moment; where the page cannot write to the clipboard, it selects the text
  instead and says Selected. `mono` sets a bare token in monospace, broken
  anywhere; a sentence breaks at its spaces, and `children` shows it with
  parts marked (`value` is still what is copied). A marked part (an address,
  a key) wraps like the words around it, breaking only when it is longer than
  the line, so give the field the width for it. `name` is what the button
  says it copies, to a screen reader, when the label does not say it. One
  thing to copy has one button: a message that holds a key is copied as a
  whole, not beside a second button for the key. A secret shown only once
  says so in the note, quietly, never in a warning.
- An error that belongs to one field is that sentence and the field's edge,
  never a notice.

## Choices

- **`Checkbox`**: a choice saved with a form. Every other attribute (`name`,
  `value`, `required`) goes on the `<input>`.
- **`RadioGroup`**: one of a few choices when each needs a sentence.
- **`Switch`**: on or off, applied the moment it changes. It needs a name
  (`label`), and the switch alone shows its state: no "On" badge beside it.
- **`SegmentedControl`**: two to five short choices that apply at once
  (Light / Dark, Degrees / Seconds), as one control: a single 1px
  `line-strong` outline, the segments divided by 1px lines with no gap and no
  padding, and the chosen segment shown by a fill, the primary's tint with its
  ink (`bg-primary-soft text-primary-ink`, like the chosen item in a nav). No
  track, no raised thumb: a padded well around segments reads as a thick
  border. Keyboard focus is the 2px outline drawn inside the segment. More
  choices, or longer ones, is a `Select`. A group of action buttons that
  belong together (the jog control's counterclockwise, Stop and clockwise) is
  built the same way, one outline and a line between them.

## Settings

- **`SettingRow`**: one setting, its name and a sentence on the left, its
  control on the right, stacked on a narrow screen. Rows go in a
  `divide-y divide-line` list inside a flush `Panel`. `below` holds what
  belongs to the setting but is wider than a control (a chart, sub-settings),
  in a well under the row.
- **A setting changed from its default** says so on its row: `changed`
  gives the row the primary's tint (a fill, like every state), and one
  button beside its name, "Reset to 6 /min" (`defaultText`), puts the
  default back through `onreset`. The button sits on the name's line at the
  name's height, so the row never jumps while a value is typed. No outline,
  no icon without words, and no amber: a changed value is a choice, not a
  warning. Pointing at the button shows a tooltip saying what the default
  is: "Default: 6 /min", or `defaultHelp` when a choice's name alone does not
  say what it does ("Automatic: turn the channel forward until it clears.").
  Every setting with a default that can be changed works this way, a
  segmented control as much as a number.
- **`tags`** puts a `Badge` or two beside a setting's name: where it acts,
  that it is happening now.
- **A setting that applies at once** (a switch, a segmented control) needs no
  Save.
- **Settings saved together** save with one primary in the panel's footer,
  next to the way back. While it saves the button shows the Spinner; after,
  a sentence in the footer says so. A failed save keeps what was typed and
  puts an `Alert` above the footer.
- **`Disclosure`**: settings most people never touch, closed until asked
  for. It sits in a divided list like any row.

## Panels

- **`Panel`**: the surface plane, one job's worth of content, with no border
  and no shadow. `title` and `description` head it, `actions` sit at the right
  of the head, `footer` gets the one line above it. `flush` drops the body's
  padding for a divided list, a table or a picture that runs to the edges.
  `fill` takes the height the layout gives it and scrolls the body inside.
- **`MediaTile`**: a camera feed or a photo. A strip with the name and its
  controls, then the picture on the media backdrop; `overlay` puts chips over
  the picture, in a dark subtree. **The tile hugs its picture:** the picture's
  box takes the picture's own shape, read from the natural size of the `<img>`
  or `<video>` inside once it loads, with `aspect` (a CSS ratio, `"16 / 9"`
  by default) as the shape until then. So a feed never shows a bar above and
  below it or down its sides. A layout gives a tile a width and lets the
  height follow, never a height the picture would not fill; a dashboard that
  fits the window sizes the whole group of tiles so the pictures fill it
  ([layout.md](layout.md#the-dashboard-layout)). `header={false}` is a tile
  that is only the picture: the name stays for a screen reader, and `actions`
  go over the picture with `overlay`, on the scrim. `expandable` adds a full
  screen button: the tile itself fills the window on the media plane (so a
  live feed is not loaded twice), and "Exit full screen" or Escape brings it
  back; `bind:expanded` drives it from code. Full screen is the one place a
  picture has bars, because the window has its own shape.
- **A part's picture is not a media tile.** A part's image (a piece on the
  dashboard, in a list, on a bin) sits straight on the plane under it, a
  panel or a row, with no grey box and no well behind it. A camera feed is
  the media plane's; a part is a picture on the page.
- **`Card`**: a panel that is one thing to open, a machine or a profile. The
  whole card is a link (`href`) or a button (`onclick`), named by `label`;
  the pointer anywhere on it fills it a step (`hover`, then `pressed`), with
  no shadow, no lift and no heavier line. Links and buttons inside it still
  work on their own, so a card never needs a click handler on a `<div>`.

## Notices

**`Alert`**: the one shape for a message in the flow of a page, in four
tones: `info`, `success`, `warning`, `danger`. A tint of the tone, its icon, a
title and a sentence, and `actions` when there is something to do about it.
No border, and never a stripe down one side. Severity is the tone, never the
layout; a fifth kind of message is a panel, not a new notice.

- A notice sits next to what it is about: above the panel whose save failed,
  above the list that is empty for a reason.
- A fault that stops the whole machine is a banner directly under the top
  bar, on every page: the danger tint, the fault's title and sentence, and a
  Details button that opens a `Modal` with the whole message and the way
  back (Home again). The top bar owns the line between them, so the banner
  is only a fill. The site's Notices page shows it.
- A notice stays until what it says stops being true. There are no toasts.

## Data

- **`Badge`**: a short state or count beside what it describes. A tint and
  the tone's ink (`neutral`, `primary`, `info`, `success`, `warning`,
  `danger`), no border. `dot` puts a status dot before the text.
- **`Stat`**: a number and its name. Stats in a row are a grid of cells:
  `grid gap-px bg-line`, each cell with its own fill.
- **Tables** use the `.data-table` class: a head of labels, one line under
  it and between rows, no outer border and no vertical lines, so a table
  sits in a flush `Panel`. `num` on a numeric column right-aligns it in the
  number style; `is-link` on a row that opens something highlights it under
  the pointer. A wide table scrolls sideways inside its panel.
- **`KeyValue`**: facts about one thing, one line between pairs; `mono` for
  a value someone might copy.
- **`ProgressBar`**: how far along, when that is known. A track and a fill
  in the primary, or in a status tone when the level means something.
- **`EmptyState`**: what an empty list shows, in a well: what would be here
  and, when there is one, the action that fills it.
- **Charts** are SVG drawn in the component, on a well: a series is 1.5px in
  the primary (`vector-effect: non-scaling-stroke`), gridlines are `line`,
  labels are 12px muted. No chart library, and no legend where one series
  needs none.

## Navigation

- **`TopBar`** and **`Wordmark`**: the first level ([layout.md](layout.md)).
  The wordmark is the primary square and the app's name in sentence case,
  "Sorter" or "Hive". Below the width where the pages and the right side fit
  side by side (`collapse`, 768px by default), the pages fold into one menu
  named for the current page. Nothing on the right switches light or dark:
  that is a setting.
- **`PageHeader`**: a page's title, its one sentence and its own actions,
  first in the page's column ([layout.md](layout.md#a-page)).
- **`SideNav`**: the second level, a column on the surface plane.
- **`Tabs`**: views of one thing, in a page or at the top of a flush panel.
  The current tab's mark replaces the bar's line under it. Arrow keys move
  between tabs. Tabs that do not fit scroll sideways without a scroll bar. The pages of the app are the top bar's and the side nav's,
  not tabs.

## Color

**`ColorPicker`**: the operator's primary, the LEGO colors as a grid of
squares, the chosen one ringed in ink and named under the grid. Each square is
a radio, so the arrow keys move through them.

## Profiles

How a sorting profile is shown, in Hive and on a machine: parts, rules and
bins, each laid out the same wherever it appears. A person reads a profile
by looking at it, so nothing is decoded from a field name, a list of IDs or
a UUID. The site's Profiles page shows each one on real catalog data.

- **`PartTile`**: one part, always in the same order and the same place: the
  picture, the name, the BrickLink ID in tabular figures, the Rebrickable
  number only when it is a different one (`3010 · RB 3010a`), then the color
  and the count. The BrickLink ID comes first because it is what a sorter
  reports a piece by; the Rebrickable number is shown only when it tells
  someone something the first does not. Laid out the same, a list of a
  hundred parts is read by running down one column, and the ID is never
  somewhere else. `layout="row"` is a line of a list: a 48px picture, the
  text, then the count and any `children` (a color select, a quantity field)
  at the end; a row owns its side padding like any row in a flush panel
  (`padded={false}` inside one that pads), and when the row itself is narrower
  than 40rem its `children` drop under the text, in line with it.
  `layout="tile"` is a square picture over its name, for a grid: the
  picture's box is the same size in every tile, and the name takes two lines
  whatever its length so the ID under it stays in line. A count alone is
  "×4"; with `found` it is a kit's progress, "3 / 6" over a bar, and it
  turns green with a check when complete. With `href` or `onclick` the whole
  part is the target, like a `Card`.
- **A part's picture is shown whole, on whatever it sits on** (`PartImage`):
  contained, never cropped, with no well, no dark backdrop and no bars
  ([surfaces.md](surfaces.md#media)). A part with no picture, or one that
  fails to load, shows a quiet blank square in its place, never the
  browser's broken-image icon and never an "image off" icon.
- **`ColorChip`**: a color as a small swatch of its RGB with a 1px
  `line-strong` hairline around it, so white and clear still read, then its
  name. The catalog gives RGB as six hex digits with no `#`; a missing or
  malformed one draws no swatch. The swatch is data, one of the few colors
  that is not a token ([color.md](color.md#what-never-appears-in-markup)).
- **`ConditionList`**: a rule's conditions as phrases, every one built the
  same way: the field, the operator in words ("is one of", "is at most",
  "matches"), then each value as a chip. A color is its swatch and name, a
  part its small picture, name and ID, a category its name, a number its unit
  ("4 studs", "$0.25"), a pattern in the mono. Conditions joined by "all of"
  or "any of" say so once above them, and a group inside a rule is indented
  under its own. `limit` is how many chips a condition shows before "+N
  more", which opens the rest in place. A condition that cannot be
  evaluated yet is in the warning tone. A rule for one part (BrickLink ID
  3001) is one phrase with one chip.
- **`ProfileBin`**: one of a profile's rules or categories (never called a
  "bin" on a page: bins are the machine's), as a card or a row. The card shows
  what a person needs to know about where pieces go: the picture (a color
  bin shows its color, a kit its picture, "Everything else" a quiet glyph),
  its place in the order, the name, what kind of bin it is (Rule, Kit,
  Category, Color, Everything else, left off when it is the name), how much it
  takes in words, its conditions, example parts only when a page asks for
  them (`examples`: rows, two to a line; a kit's get a line each, with their
  color and count), and what is
  wrong with it in the warning tone at its foot. The count is what the bin
  does: "72 parts in 8 colors", "14 parts · 96 pieces" for a kit, "Any part
  in this color" for a color bin. A rule that only tests colors takes any
  part in them, so it says "Any part in 6 colors": the parts the catalog
  knows in those colors are how it is pictured, not what it takes. A kit
  with `progress` adds "Found 41 of 96" over a bar. `layout="row"` is one
  line for a long list (a profile sorted by color has hundreds of bins): the
  place, the picture or color, the name, the count, any warnings, the kind,
  and a kit's progress; down a list of colors it leaves out "Any part in
  this color", which every row would say. `selected` takes the primary's
  tint, `plane="well"` is for a card on a dialog (itself a surface), and a
  bin from a version saved before bins were described has only a name and
  shows as a plain, name-only bin, with no picture to hold a place for.
- **Why every part looks the same.** A profile is hundreds of parts and
  dozens of rules, read by someone deciding what a machine will do with a
  piece; what they need is to find the ID, the name and the color in the
  same place every time. The old views gave each part its own arrangement of
  words, or a table of field names, and could only be read by decoding them.

## Overlays and loading

`Popover`, `Menu`, `Tooltip`, `Modal`, `Sheet` and `Lightbox` are in [overlays.md](overlays.md);
`Spinner` and `Skeleton` are in [loading.md](loading.md).

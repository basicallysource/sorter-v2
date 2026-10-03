# Color

Neutrals for structure, the primary for what someone acts on, and four LEGO
colors for status. Every color is a token with a light and a dark value, in
`src/app.css`. The site's Color page shows every token in both modes at once,
with the contrast of each text color measured from what the browser draws.

## How the tokens work

Each color is a plain custom property (`--canvas`, `--ink`, `--primary`)
declared twice: for light mode on `:root` and on any element with the class
`light`, and for dark mode on any element with the class `dark`. An
`@theme inline` block maps each one to Tailwind's name, so `bg-canvas`,
`text-ink` and `border-line` exist and each reads the property where it is
used.

- **Dark mode** is the class `dark` on `<html>`. So markup never needs a
  `dark:` modifier: a component that names tokens is right in both modes.
- **Any subtree can fix its mode.** An element with `light` or `dark` gets
  that mode's values inside it, whatever the page's. The controls over a
  camera feed use this (always dark), and so do the two columns of the Color
  page.
- **In an arbitrary value, name the property**: `border-(--primary)`,
  `var(--line)`. `var(--color-primary)` would read the page's mode, not the
  subtree's.
- **The mode** comes from the reader's stored choice, else their system's
  preference, and is applied by a script in `app.html` before the first
  paint, so a dark page never flashes light.

## The neutrals

| Token         | Light     | Dark      | For                                                          |
| ------------- | --------- | --------- | ------------------------------------------------------------ |
| `canvas`      | `#eceae5` | `#0e0e0d` | The page                                                     |
| `surface`     | `#ffffff` | `#1b1b19` | A panel, the top bar, the side nav                           |
| `well`        | `#f4f3ef` | `#141413` | Sunk into a panel                                            |
| `raised`      | `#ffffff` | `#242422` | What floats                                                  |
| `field`       | `#ffffff` | `#141413` | The inside of a field                                        |
| `track`       | `#e6e4de` | `#0f0f0e` | The groove of a progress bar                                 |
| `line`        | `#e2dfd8` | `#2e2d2a` | A line between items                                         |
| `line-strong` | `#b9b4aa` | `#4a4843` | The outline of a field, a select, a checkbox                 |
| `ink`         | `#1b1a18` | `#eeece7` | All text that matters                                        |
| `ink-muted`   | `#686460` | `#a39f96` | Help, descriptions, labels                                   |
| `ink-faint`   | `#9d988f` | `#6f6c65` | Placeholders, what is off. Never something someone must read |

`media` (black, so a feed still stands off the dark canvas), `knob` (the switch's knob, white) and `scrim` (behind a
dialog) are the same in both modes. `hover`, `pressed` and `soft` are ink at
5%, 9% and 7%, so they darken a light plane and lighten a dark one.

## The primary

On a machine the operator picks the primary from 64 LEGO colors
(`src/lib/lego-colors.ts`, `ColorPicker`), and the machine keeps it so every
browser pointed at it agrees. Hive's primary is LEGO red, fixed. The default
is LEGO blue, `#0055BF`.

The colors that depend on the primary's contrast are worked out, not listed,
by `applyPrimary` in `src/lib/theme.svelte.ts`:

- `on-primary`: the text on a primary fill, white or ink, whichever reads
  better on that color.
- `primary-ink`: the primary as text. It is moved toward black in light mode
  and toward white in dark mode until it reaches 4.5 to 1 on the hardest
  background it is used on (its own tint over the canvas in light mode, over
  the raised plane in dark mode). Both are set on `<html>`, so a subtree of
  either mode reads right.
- `primary-hover` and `primary-soft` (the chosen item's tint) are mixed from
  the primary in CSS.

The primary marks what someone acts on and where they are: the primary
button, the current page and tab, the chosen item, a switch that is on, a
checked box, links, the focus outline.

## The status colors

LEGO green `#00852B`, yellow `#FFD500`, red `#D01012` and blue `#0055BF`, the
same in both modes and whatever the primary.

| Status  | Means                                      | Tint           | Text on a surface or the tint | Text on the solid color |
| ------- | ------------------------------------------ | -------------- | ----------------------------- | ----------------------- |
| success | Running, done, connected                   | `success-soft` | `success-ink`                 | `on-success` (white)    |
| warning | Needs attention                            | `warning-soft` | `warning-ink`                 | `on-warning` (dark ink) |
| danger  | Failed, stopped, or will destroy something | `danger-soft`  | `danger-ink`                  | `on-danger` (white)     |
| info    | Information                                | `info-soft`    | `info-ink`                    | `on-info` (white)       |

- Warning is LEGO yellow, `#FFD500`. The apps' own tokens still say
  `#F2A900`, an amber, until they adopt the system.
- `warning-ink` turns yellow in dark mode, so it can never be the text on the
  yellow fill. Text on a `bg-warning` fill is `on-warning`, a dark ink that is
  the same in both modes because the yellow is.
- A status color never decorates. If the primary is the same color as a
  status, the status still wins on its own component.
- A notice or a badge is its tone's tint, with no outline.

## Contrast

Text reaches 4.5 to 1 on what it sits on, in both modes, measured on the
Color page. Faint ink does not, on purpose: it is only for what can be
skipped.

## What never appears in markup

- A hex value, or any color literal.
- Tailwind's own palette: `bg-white`, `text-black`, `bg-gray-100`,
  `text-rose-600`. None of it follows the mode.

The exceptions are data that is a color (`src/lib/lego-colors.ts`, a part's
color in a list, the swatches on the Color page), categorical colors drawn
over a photo, and static images such as favicons.

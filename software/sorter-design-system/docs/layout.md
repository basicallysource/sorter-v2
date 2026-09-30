# Layout

The app shell, the two layouts every screen is one of, and the spacing and
sizes that keep them in line. Layout does the grouping, so nothing needs a
box around it to belong together.

## The shell

- **The top bar** (`TopBar`, with `Wordmark`) is on the surface plane and
  owns the one line under it. It holds the mark, the app's pages, and on the
  right what applies everywhere (the machine, its status, the profile). The
  current page's mark is as wide as the link and `--indicator` thick, and sits
  on the bar's line in place of it.
- **Light or dark is a setting**, never a control in the top bar: Settings >
  General on a machine, the account's settings on Hive, next to the primary
  color where there is one. It is chosen once, not reached for on every page.
- **On a narrow screen the top bar folds.** Where the pages and the right
  side no longer fit side by side, the pages become one menu, its button
  named for the current page ("Dashboard"), with the current page checked.
  The bar never scrolls sideways and never cuts a page's name off. `collapse`
  sets the point as the bar's own width: `md` (768px) by default, `lg` or
  `xl` for more pages or a busy right side (Hive's seven pages). It is a
  container query, so a server-rendered page folds before any script runs.
- **An app screen is exactly the window** from the `lg` breakpoint up: the
  top bar, and under it an area that fills the rest (`h-dvh` on the shell, a
  flex column, `min-h-0` on what may shrink). The page itself never scrolls;
  what can grow (a list, a settings column) scrolls inside its own panel or
  column (`Panel`'s `fill`). On a phone it is one column that scrolls.
- **The side nav** (`SideNav`), when a page has one, is a column on the
  surface plane, the full height beside the content, which sits on the
  canvas. There is no line between them: their fills differ. The current
  section takes the primary's tint; a group's name is a `label`.

## The settings layout

The side nav on the left (240px), and the page's panels on the canvas beside
it, left-aligned, each column scrolling on its own. A page of panels and
forms is at most 1152px wide, a comfortable line for reading a setting. Below
`lg` the side nav becomes a `Select` above the page. A page is a title and one
sentence, then panels, one per job, 16px apart; see the example app's General
page.

**A page whose main thing is a camera** (a channel page) is not a page of
forms, so it takes the whole content width, capped at 1800px on a very large
screen. From `xl` up the camera takes all the width the stepper's panel
leaves (23rem, on the right), and below `xl` the stepper's panel goes under
the camera; whatever else the page has (the C4 sectors) is below both. The
stepper's controls are one control: a jog control (counterclockwise, Stop and
clockwise, in one outline with a line between them), the step presets and the
speed, not a row of loose buttons or a padded track.

## The dashboard layout

From `lg` up the dashboard is exactly the window: the cameras on the left,
one column on the right with the status, the numbers, the recent pieces (they
scroll inside their panel) and the runtime. On a phone the status and its
Home come first, then the cameras, then the pieces: the page's order in the
markup is the phone's order.

**The cameras are laid out to their pictures, not to the space.** A camera
tile is its picture (the strip, then a box of the feed's own shape,
[components.md](components.md#panels)), so a layout gives the group of tiles
a width and lets the pictures set the heights. Two feeds share the first row
and the third takes the whole second row. The group is as wide as the
window's height allows, so its pictures fill the height exactly; the right
column takes the rest of the width, from 19rem to 40rem, and on a screen
wider than that the two are centered. Nothing is stretched, so nothing has a
bar.

The example app's dashboard does it with a size container (the row that holds
both, `container-type: size`) and container units, from the pictures' shape
(`--feed`, the height of a picture over its width, `9 / 16` for 16:9) and the
strips and the gap that do not scale:

```
--cameras: min(
	100cqw - 19rem - var(--gap-panels),                       /* the width left after the column's least */
	(100cqh - 2 * var(--size-control-lg) - (1 - var(--feed) / 2) * var(--gap-panels))
		/ (1.5 * var(--feed))                                 /* the width the height allows */
);
```

Two strips of `--size-control-lg`, one gap, and two rows of pictures (each of
the first row's is half the group's width less the gap, the second row's the
whole width) add up to the height of the container; solving for the width
gives the second line. A feed with another shape changes `--feed` and the
`aspect` the tiles start with, and nothing else.

## A page

- A title (`text-xl`) and one sentence (`text-sm text-ink-muted`) on the
  canvas, then the panels: `PageHeader`, with the page's own actions (New
  profile, Add a machine) at its right. On a phone the actions wrap under
  the sentence.
- The page is a column with `gap-(--gap-panels)`: the header, then the
  panels. The header has no margin of its own.
- A panel's title says what it is for; a page needs no second heading level
  above its panels.
- One primary action per panel or dialog, at the right of its footer, after
  the way out.

## Spacing

A 4px grid and a short list of steps, each used for one job everywhere.

| Step | For                                                                     |
| ---- | ----------------------------------------------------------------------- |
| 4    | An icon and its word in a small control; a label and its sentence       |
| 8    | Controls in a row; the least gap between two outlined things            |
| 16   | Between panels (`--gap-panels`); a page title and the first panel       |
| 20   | A panel's side padding (`--pad-panel`), so title, rows and footer align |
| 24   | Around the page on a wide screen (16 on a phone)                        |
| 32   | Between the side nav and the content                                    |

## The size scale

Every size a control has comes from one set of tokens, so everything steps
together and nothing reads cramped next to its neighbor.

| Token                      | Size    | For                                   |
| -------------------------- | ------- | ------------------------------------- |
| `--size-control`           | 36px    | A button, a field, a select           |
| `--size-control-sm`        | 30px    | The same in a dense row               |
| `--size-control-lg`        | 44px    | The jog buttons, a media tile's strip |
| `--size-badge`             | 22px    | A badge                               |
| `--switch-w`, `--switch-h` | 40 x 22 | A switch                              |
| `--size-topbar`            | 48px    | The top bar                           |
| `--size-nav-item`          | 32px    | A side nav item                       |
| `--size-tab`               | 40px    | A tab                                 |
| `--size-menu-item`         | 34px    | A menu or select item                 |
| `--indicator`              | 3px     | The current page's or tab's mark      |
| `--pad-panel`              | 20px    | A panel's side padding                |
| `--pad-row`                | 14px    | A row's top and bottom padding        |
| `--gap-panels`             | 16px    | Between panels                        |

Use them through Tailwind's variable syntax: `h-(--size-control)`,
`px-(--pad-panel)`.

## Narrow screens

Everything works at 390px wide: the top bar folds its pages into one menu
named for the current page, the side nav turns into a select, a row stacks
its control under its name, a page's actions wrap under its title, and no
page scrolls sideways.

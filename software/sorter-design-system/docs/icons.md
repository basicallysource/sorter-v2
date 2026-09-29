# Icons

Lucide, and only Lucide, from the `@lucide/svelte` package. An icon backs up
a word; alone, it is an icon button with a name.

## Using one

Import each icon on its own, never the whole set:

```svelte
import Camera from '@lucide/svelte/icons/camera';

<Camera size={16} />
```

- **Sizes.** 16 in text and in controls, the default. 14 in a small button
  or beside 12px text, 18 in a notice, 24 alone in an empty state. Nothing
  larger.
- **Stroke.** Lucide's own, unchanged.
- **Caps and joins.** Square caps and mitred joins, like the nearly square
  corners. The `.lucide` rule in `app.css` does this; a component never sets
  it.
- **Color.** `currentColor`, always: an icon is text and takes the color of
  the words beside it. A notice's icon takes its tone's ink.

## Never

- Draw one. No hand-written `<svg><path>` in a component: it sits at a
  different weight from Lucide's and nobody can review the path data. If
  Lucide has nothing for it, use a word.
- Leave one alone. An icon with no word next to it is an icon button, and an
  icon button has a name (`Button`'s `label`), which the pointer shows.
- Spin one. A refresh icon stays still while its button shows the Spinner.

The brand marks (the basically brick, the wordmark) are the one exception to
Lucide, and each lives in one component.

## One icon per meaning

| Meaning                                | Icon                                                      |
| -------------------------------------- | --------------------------------------------------------- |
| Close                                  | `x`                                                       |
| Add, new                               | `plus`                                                    |
| Rename, edit                           | `pencil`                                                  |
| Delete                                 | `trash-2`                                                 |
| Duplicate, copy                        | `copy`                                                    |
| Download a file                        | `download`                                                |
| Rescan, reload                         | `refresh-cw`                                              |
| Settings                               | `settings`                                                |
| Home the machine                       | `house`                                                   |
| The machine's power menu               | `power`                                                   |
| Start sorting, pause                   | `play`, `pause`                                           |
| Stop a motor                           | `square`, filled                                          |
| Rotate a camera                        | `rotate-cw`                                               |
| Aim, calibrate a position              | `crosshair`                                               |
| A camera, a feed                       | `camera`                                                  |
| Storage layers                         | `layers`                                                  |
| Hive                                   | `cloud`                                                   |
| Connect                                | `plug`                                                    |
| Search                                 | `search`                                                  |
| Opens a list below                     | `chevron-down`                                            |
| Opens a section; jogs clockwise        | `chevron-right`                                           |
| Jogs counterclockwise                  | `chevron-left`                                            |
| Back to where you were                 | `arrow-left`                                              |
| Goes somewhere else                    | `arrow-right`                                             |
| Leaves the app                         | `arrow-up-right`                                          |
| More actions (a menu)                  | `ellipsis`                                                |
| Chosen, done                           | `check`                                                   |
| Light mode, dark mode                  | `sun`, `moon`                                             |
| Info, success, warning, danger notices | `info`, `circle-check`, `triangle-alert`, `octagon-alert` |

A new meaning gets a row here before it gets an icon. The site's Icons page
shows them all.

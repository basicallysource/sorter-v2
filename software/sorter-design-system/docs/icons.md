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
| Fork: a profile of your own from one   | `git-fork`                                                |
| Download a file                        | `download`                                                |
| Upload a file or a picture             | `upload`                                                  |
| Publish, public                        | `globe`                                                   |
| Save                                   | `save`                                                    |
| Save to your library                   | `bookmark-plus`                                           |
| Swap for another                       | `replace`                                                 |
| Move up, move down in a list           | `arrow-up`, `arrow-down`                                  |
| Drag to reorder                        | `grip-vertical`                                           |
| Turn on, turn off                      | `toggle-right`, `toggle-left`                             |
| Rescan, reload                         | `refresh-cw`                                              |
| Settings                               | `settings`                                                |
| Home the machine                       | `house`                                                   |
| Start the hardware                     | `power`                                                   |
| Power the machine down                 | `power-off`                                               |
| Start sorting, pause                   | `play`, `pause`                                           |
| Stop a motor                           | `square`, filled                                          |
| Rotate a camera                        | `rotate-cw`                                               |
| Aim, calibrate a position              | `crosshair`                                               |
| A camera, a feed                       | `camera`                                                  |
| Storage layers                         | `layers`                                                  |
| Hive                                   | `cloud`                                                   |
| Connect                                | `plug`                                                    |
| An API key, a token                    | `key-round`                                               |
| AI, an assistant                       | `sparkles`                                                |
| Send a message                         | `send`                                                    |
| A kit                                  | `boxes`                                                   |
| A profile's rules, a filter            | `funnel`                                                  |
| A picture                              | `image`                                                   |
| Where a piece goes                     | `corner-down-right`                                       |
| Search                                 | `search`                                                  |
| Opens a list below                     | `chevron-down`                                            |
| Opens a section; jogs clockwise        | `chevron-right`                                           |
| Jogs counterclockwise                  | `chevron-left`                                            |
| Back to where you were                 | `arrow-left`                                              |
| Goes somewhere else                    | `arrow-right`                                             |
| Leaves the app, or opens a new tab     | `arrow-up-right`                                          |
| A button that opens a menu             | `ellipsis`, three dots                                    |
| Chosen, done, yes                      | `check`                                                   |
| Light mode, dark mode                  | `sun`, `moon`                                             |
| Info, success, warning, danger notices | `info`, `circle-check`, `triangle-alert`, `octagon-alert` |

A new meaning gets a row here before it gets an icon. The site's Icons page
shows them all.

## A menu's button is three dots

A button that opens a menu shows three dots (`ellipsis`), never the icon of
one of the actions inside. The machine's menu (restart the backend, restart
the machine, power down) opens from three dots named "System", not from a
power icon: a power icon says the button powers something off, and pressing
it would be a surprise. `power` and `power-off` belong to the menu's items,
next to their words. Only a button that opens a list of choices for the
current value, a `Select` or a switcher, shows `chevron-down` instead.

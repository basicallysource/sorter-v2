# Apps

Which sites follow this system, what is different in each, and where each
keeps its copies of the tokens and components.

| Site                              | Folder                                                                           | Primary                                                           | Favicon                       |
| --------------------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------- |
| The Sorter UI, a machine's own UI | `software/sorter/frontend`                                                       | LEGO blue `#0055BF` by default; the operator picks any LEGO color | blue                          |
| Hive                              | `software/hive/frontend`                                                         | LEGO red `#D01012`                                                | red                           |
| The docs site                     | `docs`                                                                           | LEGO red `#D01012`                                                | yellow                        |
| The parts calculator              | `parts-calculator`                                                               | LEGO blue `#0055BF`                                               | the plain brick, no color yet |
| The SorterOS setup site           | `software/sorteros/sorteros-setup`                                               | LEGO blue `#0055BF`                                               | the plain brick, no color yet |
| The Wi-Fi setup page              | `software/sorteros/portal/frontend`                                              | LEGO blue `#0055BF`                                               | none                          |
| The first-boot progress page      | inline in `software/sorteros/build/overlay/usr/local/sbin/sorteros-firstboot.py` | LEGO blue `#0055BF`                                               | none                          |

## Where they stand

The three SorterOS pages are on the system: they carry `src/app.css` from here
(the Wi-Fi page and the setup site as the file itself, the first-boot page as
its values, inline) and the components here, copied unchanged. The Sorter UI
and Hive still carry the tokens the Sorter UI had before this system existed
(`bg`, `surface`, `border`, `text`, `text-muted`) and primitives of their own,
and move in their own changes. The docs site and the parts calculator keep
their own for now. New work in any site follows the rules here, with the
tokens that site has.

The system uses the `@lucide/svelte` package, as the SorterOS pages do; the
Sorter UI, Hive and the parts calculator use the older `lucide-svelte`. The
icons and their names are the same, and a site moves to `@lucide/svelte` when
it takes the components.

## The Sorter UI

- Tokens: `src/routes/layout.css`. Components: `src/lib/components/`, with the
  Spinner in `Spinner.svelte` and the primitives in `primitives/` (exported from
  `primitives/index.ts`).
- The primary is the operator's pick from the LEGO palette
  (`src/lib/lego-colors.ts`, chosen with `src/lib/components/LegoColorPicker.svelte`).
  It is saved on the machine (`/api/settings/theme`), so every browser pointed
  at that machine shows the same color; `src/lib/stores/themeColor.svelte.ts`
  applies it. This system's `src/lib/theme.svelte.ts` shows how the primary and
  the colors that depend on its contrast are applied.
- Light or dark and the primary are set in Settings > General, not from the
  top bar.
- Raw hex on purpose: `src/lib/lego-colors.ts`, which is the LEGO color data.
- One deliberate side stripe: the servo inventory card
  (`src/lib/components/setup/servo/ServoInventoryCard.svelte`, colors set in
  `SetupServoOnboardingSection.svelte`) marks each servo's hardware state with
  a colored stripe down its left edge. It is the only one.
- One drawing of the machine: the chute flap
  (`src/lib/components/servo/ChuteFlapDiagram.svelte`), a cross-section of a
  layer's flap open and closed, on the storage layers page. Like a chart it is
  drawn in the component from the tokens, and it is a figure, not an icon.
- Fonts: IBM Plex Sans (variable) and IBM Plex Mono, self-hosted with
  `@fontsource`, because a machine may have no internet.
- Favicon: blue, from `static/`, linked in `src/app.html`.

## Hive

- A public community site, with the same corners as everything else: its
  badges are the system's `Badge`, and its cards, panels, buttons, fields,
  notices and dialogs take the corner tokens. A person's avatar is the one
  round shape besides a status dot (`rounded-full`).
- The primary is LEGO red and cannot be changed. Light or dark comes from
  `src/lib/stores/theme.ts`: the reader's stored choice, else the system's
  preference. The reader sets it in their account's settings, not from the
  top bar.
- It renders on the server (the Node adapter, SSR on), so the components are
  written to render there too ([engineering.md](engineering.md#server-rendering)).
- Tokens: `src/app.css`. Hive's `canvas` token is the near-black backdrop behind
  photos, the same in both modes; here that is `media`, and `canvas` is the
  page.
- Components: `src/lib/components/Spinner.svelte` and the primitives in
  `src/lib/components/primitives/`.
- Raw colors on purpose: the categorical palettes drawn over sample photos
  (`src/lib/components/sample/bbox-helpers.ts`, the annotator's box palette,
  the model comparison palette, and the two midpoints of the coverage ramp in
  `Sparkline.svelte` and `DiversityDonut.svelte`), which never sit on a themed
  surface; the scrim under a dialog (`bg-black/50`) and chips floating on a
  photo; static assets and favicons.
- Fonts: IBM Plex from Google Fonts.
- Favicon: red, from `static/`, linked in `src/app.html`.

## The docs site

- Tokens: `src/routes/layout.css`, with red as the primary. The markdown
  components (callouts, figures, image rows) are this site's own, in the same
  file and `src/liquid/_includes/`; `docs/AGENTS.md` describes them.
- Fonts: IBM Plex from Google Fonts.
- Favicon: yellow, from `static/assets/`, linked in `src/app.html`.

## The parts calculator

- Tokens: `src/routes/layout.css`. Fonts: IBM Plex from Google Fonts.
- Favicon: the plain brick with no colored square, so it needs a color of its
  own (Favicons, below).

## The SorterOS pages

- **The setup site** (`software/sorteros/sorteros-setup`, where an SD card
  image is customized before flashing, served as a static site): the system's
  `src/app.css`, Geist self-hosted, and the components. Light or dark follows
  the reader's system, with no toggle, since the page is used once. Its
  favicon is the plain brick and needs a color of its own.
- **The Wi-Fi setup page** (`software/sorteros/portal/frontend`) runs in a
  phone's captive-portal window, over plain HTTP, with no internet. It copies
  `src/app.css` unchanged and adds one block after it, for what that window
  needs:
  - no web font: it loads none, so the stack's fallbacks (the phone's
    `system-ui` and `ui-monospace`) are what it shows;
  - light or dark from the phone (`prefers-color-scheme`), not a stored
    choice;
  - the touch sizes: 44px controls, because it is used with a thumb.
- **The first-boot progress page** (inline in
  `software/sorteros/build/overlay/usr/local/sbin/sorteros-firstboot.py`) is
  served while nothing else on the machine answers, so everything in it is
  inline: the tokens as values, the Spinner as CSS, Lucide's check, x and
  clock paths as inline SVG. Like the Wi-Fi page it uses the reader's own
  fonts and follows the browser's light or dark.

## Favicons

People keep several of these sites open side by side, and a row of tabs with
identical bricks tells them nothing. So the mark is the same everywhere and the
color says which site it is: the basically brick (black outline, white fill)
on a full-bleed colored square.

| Site                      | Color                            |
| ------------------------- | -------------------------------- |
| Hive                      | `#D01012`, LEGO red              |
| The docs site             | `#FFD500`, LEGO yellow           |
| A machine (the Sorter UI) | `#0055BF`, LEGO blue             |
| This design system's site | `#6C6E68`, LEGO Dark Bluish Gray |

These are palette values that already existed, not new ones. The color is for
the favicon only: it does not tint headers, chrome or accents, and nothing else
in a site reads it.

- **The brick** is the outlined, white-filled basically logo, transparent
  outside the brick. Composite it, do not redraw it: building the mark from
  `basically-logo.svg` means adding stroke weight to keep the lines alive at
  small sizes, and that comes out visibly too bold. Crop to the alpha bounding
  box, size the brick to 92% of the frame's width, center it, and render each
  size at its own resolution instead of scaling one master down.
- **The field** is a square with sharp corners, not a circle and not a rounded
  square. A square gives the color about a third more area than a circle in the
  same box, which is what makes the site recognizable at 16px. At 92% a colored
  margin survives against a white browser toolbar; at 96% the brick's corners
  touch the edge.
- **Four files** in each site's static folder: `favicon.ico` (16, 32 and 48 px,
  the sizes a tab uses), `favicon-96.png` and `favicon-192.png`, and
  `apple-touch-icon.png` (180 by 180, for a phone's home screen). Link them in
  `src/app.html`, not in a `<svelte:head>`: the icon never changes, so it
  belongs in the shell.
- **This design system's site** runs only while someone works on it, so it
  ships one `favicon.svg`: the gray field and the brick composited from the
  logo's own paths (the outline's outer edge filled white, then the outline
  over it). Gray leaves the clearer hues for the public sites that still need
  one (the parts calculator, the SorterOS setup site).
- **A new site** needs a color that cannot be mistaken for the others at 16px,
  where the brick is a smudge and the hue is the whole signal. Check it at that
  size before choosing it. Never restyle the brick itself: a different mark per
  site defeats the point.

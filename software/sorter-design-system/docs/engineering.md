# Engineering

The code side: the stack, the files that make up the system, how an app takes
a component, and the check to run after every visual change.

## The stack

SvelteKit 2 with Svelte 5 runes, Tailwind 4, TypeScript, pnpm, the static
adapter with server rendering off, the same as the Sorter UI and Hive, so a
component behaves here exactly as it will in the app it is copied into.

```sh
pnpm install
pnpm dev      # the site
pnpm check    # svelte-check: must be clean
pnpm format   # prettier
```

## The files

| File                        | What it is                                                                               |
| --------------------------- | ---------------------------------------------------------------------------------------- |
| `src/app.css`               | Every token: colors in both modes, corners, sizes, type, the button style, a few classes |
| `src/app.html`              | Applies the stored mode and primary before the first paint                               |
| `src/lib/theme.svelte.ts`   | Light or dark, and the primary with the colors that depend on its contrast               |
| `src/lib/lego-colors.ts`    | The LEGO colors an operator can pick as the primary                                      |
| `src/lib/components/`       | The components the apps copy, and `place.ts`, which places what floats                   |
| `src/lib/site/`             | The site's own pieces (page headers, specimens); never copied into an app                |
| `src/routes/(site)/`        | The site's pages                                                                         |
| `src/routes/(app)/example/` | The example app: the Sorter UI's dashboard and settings, built from the components       |
| `docs/`                     | These files; the site renders them under Docs                                            |

The custom CSS is a short list: the tokens, `.label`, `.num`, `.data-table`
and the icon caps (`.lucide`). Everything else is a utility on the element.
A new class is a discussion, not a habit.

## How an app takes the system

1. **The tokens.** Replace the app's token block with `src/app.css` from here
   (Tailwind 4, the same `@import 'tailwindcss'`). Its old token names (`bg`,
   `border`, `text`, `text-muted`) become `canvas`, `line`, `ink`, `ink-muted`.
2. **The mode and the primary.** Copy `src/lib/theme.svelte.ts`, or on a
   machine keep the stored primary where it is (the backend) and call
   `applyPrimary` with it. Copy the pre-paint script from `src/app.html`.
3. **The fonts.** Add `@fontsource-variable/geist` and
   `@fontsource-variable/geist-mono` and import them in the root layout, as
   `src/routes/+layout.svelte` does.
4. **The icons.** Use `@lucide/svelte`, one icon at a time
   (`@lucide/svelte/icons/<name>`). The apps' older `lucide-svelte` has the
   same icons and names.
5. **The components.** Copy each file from `src/lib/components/` unchanged,
   with `place.ts` for anything that floats. Delete the app's own version of
   it, and move every use over.

A component that needs something new (a variant, a size, a prop) gets it
here first, with its example on the site, and the app copies the file again.
Never edit a copied component in an app, and never restyle a raw `<button>`,
`<select>` or `<dialog>` inline.

## Svelte conventions

- Props with `$props()`, state with `$state`, `$derived` and `$effect`.
- Events are callback props (`onclick`, `onchange`, `onclose`), never
  `createEventDispatcher`.
- Content is a snippet (`children`, `footer`, `trigger`), rendered with
  `{@render ...}`.
- A component that wraps a native element passes the rest of its attributes
  through (`...rest`), so `aria-*` and `data-*` reach the element.

## The check after a visual change

Look; do not assume. Before calling a change done:

1. `pnpm check` is clean.
2. Every page the change touches, at 1440, 1024 and 390 wide, in light and in
   dark.
3. With a light primary (LEGO yellow), a dark one (LEGO blue) and red: text
   on the primary and the primary as text both read.
4. **Seams.** Wherever two parts meet, one line or none, never two.
5. **Overflow.** Nothing scrolls sideways but a table or a list that is meant
   to; an app screen at 1440 does not scroll at all.
6. **The console** has no errors or warnings.
7. **Keyboard.** Every control is reachable with Tab, shows the focus
   outline, and anything that opens closes on Escape.

When something new breaks, write down what made it impossible in this file.

## What went wrong once

- A `::backdrop` rule without `dialog` dimmed the page under every popover,
  since popovers have a backdrop too. It is `dialog::backdrop`.
- A token defined with `var()` on `:root` is worked out there, so a light or
  dark subtree kept the page's value. Tokens that depend on the mode are
  declared on every element that sets a mode (`:root`, `.light`, `.dark`).

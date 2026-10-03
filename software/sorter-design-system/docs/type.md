# Type

Geist for words and Geist Mono for what someone copies. Five sizes, and 14px
is the smallest anyone has to read.

## The typeface

Geist, with Geist Mono ([decisions.md](decisions.md)). Both are self-hosted
with `@fontsource-variable/geist` and `@fontsource-variable/geist-mono`
(imported in `src/routes/+layout.svelte`), because a machine may have no
internet. They are `--sans` and `--mono` in `src/app.css`.

Markup never names a typeface: text uses Geist by default, `font-mono` asks
for Geist Mono, and `num` for tabular figures.

## The scale

| Role     | Size and weight       | Classes                                 | For                                                                    |
| -------- | --------------------- | --------------------------------------- | ---------------------------------------------------------------------- |
| Display  | 24px, semibold, tight | `text-2xl font-semibold tracking-tight` | The title of a page that introduces an area: these pages, a setup step |
| Title    | 20px, semibold, tight | `text-xl font-semibold tracking-tight`  | An app page's title                                                    |
| Heading  | 16px, semibold        | `text-base font-semibold`               | A panel's or a dialog's title                                          |
| Body     | 14px                  | `text-sm`                               | Everything someone reads                                               |
| Emphasis | 14px, medium          | `text-sm font-medium`                   | A setting's or a row's name, a button's label                          |
| Label    | 14px, medium, muted   | `label`                                 | A group's name in a nav, a stat's name, a table's head                 |
| Meta     | 12px, medium          | `text-xs font-medium`                   | A badge, a count, a bin code, a time: short and skippable              |
| Number   | 24px, medium, tabular | `num text-2xl font-medium`              | A stat                                                                 |

Nothing is smaller than 12px, and 12px is only for what can be skipped. There
is no 10px or 11px anywhere.

## Labels and numbers

- **Labels are sentence case**, like every other word: "Pieces a minute",
  "Hardware". Nothing on a screen is in capitals.
- **Numbers use Geist's tabular figures** (`num`), not the mono, so a number
  that changes in place lines up and does not jitter.

## Mono

Geist Mono is for what someone might copy or compare character by character:
an address, a hash, an id, a hex value, a file path. Numbers use `num`, not
`font-mono`.

## Writing

- Sentence case everywhere: titles, labels, buttons, menu items. No Title
  Case, and no capitals, for emphasis or otherwise.
- A button says what it does ("Save", "Home", "Delete profile"), never
  "Submit", "OK" or "Click here".
- Help says what a setting does, in plain words, next to it, where it is
  always visible; not in a tooltip.
- Short sentences. Facts before adjectives. No exclamation marks.
- A name that is too long truncates with an ellipsis and a tooltip; it never
  wraps a row out of line.

# Loading

The Spinner is the one moving thing that says wait.

## The Spinner

`Spinner.svelte`: four squares, one lit at a time, snapping clockwise every
quarter cycle. It is discrete, not eased; it takes the color of the text
around it (`currentColor`) and its size from `size` (12, 16, 24 or 32). It
keeps moving under `prefers-reduced-motion`, because a frozen loading
indicator reads as a hung process. It draws only itself and does not center
or pad itself: the caller places it. It is a `<span>`, so it is valid inside
a button.

Where it goes:

- **Beside a sentence** that says what is loading: "Checking the Hive
  connection". Never a sentence alone ("Loading...") and never the Spinner
  alone where there is room for the words.
- **In the button** that started the work: `Button`'s `loading` swaps its
  icon for the Spinner and keeps the label.
- **In the middle of a panel** whose content is on its way, with the
  sentence under it.

Nothing else spins: no `animate-spin`, no spinning `Loader2` or refresh icon,
no rotating ring, no pulsing dot.

## Skeletons

`Skeleton.svelte`. When the shape of what is coming is known (the rows of a
list, a picture, a number), a skeleton holds its place, so nothing jumps when
it lands. It fades gently and never spins. Put `aria-busy="true"` on the
region that is loading. When the shape is not known, it is the Spinner.

## Progress

`ProgressBar.svelte`. When how far along is known, a bar says so, with the
numbers beside it ("Copying samples", 38%). When it is not, it is the
Spinner. The bar has no stripes and no animation but its width.

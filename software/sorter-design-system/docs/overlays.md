# Overlays

What floats over the page: the popover, the menu, the select's list, the
tooltip and the modal. All of them are the raised plane: `bg-raised` with one
`border-line`, and no shadow. They render in the browser's top layer (the
`popover` attribute, or the native `<dialog>`), so no ancestor's overflow can
clip them and no z-index is needed. `place.ts` puts a floating panel next to
what opened it, on the preferred side, flipped when that side has no room,
and kept 8px inside the window.

## Popover

`Popover.svelte`. A little content that opens from a button: a picker, a
short form, an explanation too long for a tooltip. It closes on a click
outside, on Escape, and focus goes back to the button. The trigger snippet
gets the attributes that wire its button to the panel; spread them onto it:

```svelte
<Popover label="Camera exposure">
	{#snippet trigger(props)}<Button {...props}>Exposure</Button>{/snippet}
	...
</Popover>
```

## Menu

`Menu.svelte`. Actions or links from one button: the machine's power menu, a
card's "more" menu (`ellipsis`), a switcher. The arrow keys, Home and End
move, Enter chooses, Escape and Tab close. An item that destroys something
comes last, after a separator, in danger ink, and its action asks first (a
`Modal`). A switcher's items take `checked`, and the current one gets a
check.

## Select

`Select.svelte` is a field that opens a list: our own, not the browser's, so
it looks like the rest of the page on every system. From the keyboard, Enter,
Space or the arrows open it; the arrows, Home and End move; typing jumps to
the first match; Enter chooses; Escape and Tab close. The list is at least as
wide as the field and scrolls past 18rem.

## Tooltip

`Tooltip.svelte`. A short name for something with no room for one: a cut-off
value, a status dot, a mark on a chart. It shows after a short pause under
the pointer, at once on keyboard focus, and hides on Escape. An icon button
names itself (`Button`'s `label`) and needs no Tooltip. A tooltip never holds
what a setting needs to be understood: that goes under the setting, where it
is always visible.

## Modal

`Modal.svelte`, the browser's own `<dialog>`: focus stays inside it, Escape
closes it, and the page sits under the scrim. A head with the title and a
close button, a body that scrolls, and a foot with the actions: the way out,
then the one thing to do. A click on the scrim does not close it, so a
half-filled form is never lost to a stray click; the close button and Escape
always do. For a decision that stops everything else, or a short form that
belongs to nothing on the page.

A confirmation says what will happen in a sentence ("The machine stops
sorting and comes back in standby in about half a minute"), and its button
says the action ("Restart"), in `danger` when it destroys or stops something.

## What there is not

- **No toasts.** A result shows where it happened: the button's own state, a
  sentence in the panel, or an `Alert` in the flow.
- **Nothing opens on hover but a tooltip.** A touch screen has no hover, and
  a machine may have one.
- **One overlay at a time.** A menu item that needs a dialog closes the menu
  first, and a dialog never opens another. A select inside a popover is the
  one exception, because its list belongs to the popover.
- **No shadows.** The line and the fill are enough.

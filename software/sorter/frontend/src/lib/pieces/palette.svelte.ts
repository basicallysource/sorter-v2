import type { BrickLinkColor } from './colors';

// The BrickLink palette last fetched from the machine, kept where every view
// that draws a piece's color can read it: a swatch appears (and is right for
// Pearl, Trans and every other BrickLink color) as soon as it loads.
let current = $state<BrickLinkColor[]>([]);

export function currentPalette(): BrickLinkColor[] {
	return current;
}

export function setCurrentPalette(palette: BrickLinkColor[]): void {
	if (palette.length > 0) current = palette;
}

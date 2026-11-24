// How a picture sits in its slot, chosen once for the whole /layouts page.
// fill: it fills the square (its long ends are cut off; the pointer shows it
// whole). tile: whole, on a quiet square. bare: whole, on nothing.
export type Fit = 'fill' | 'tile' | 'bare';

export const pictures = $state<{ fit: Fit }>({ fit: 'tile' });

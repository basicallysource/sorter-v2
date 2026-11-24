// Shared shapes for the piece-detail panels.

export type InfoRow = {
	label: string;
	value: string;
	mono?: boolean;
	valueClass?: string;
};

// One picture of a piece, from any channel, as a FrameStrip lays them out:
// what to show, and what to say about it under the pointer.
export type Frame = {
	key: string;
	src: string;
	// Under the enlarged picture: which picture, when, and whether it was used.
	label: string;
	// It produced the applied result: drawn with a stroke around it.
	used: boolean;
	// The channel it came from ("C4"), or "—" when that was never recorded.
	channel: string;
	// How sharp it is, when it was measured (higher is sharper). Said under
	// the enlarged picture only.
	sharpness: string | null;
};

// One fact about a piece, in the page's top card.
export type Fact = {
	label: string;
	value: string;
	mono?: boolean;
	valueClass?: string;
	// A LEGO color's swatch (a hex with a leading #), drawn before the value.
	swatch?: string | null;
	// Said under the pointer.
	title?: string;
};

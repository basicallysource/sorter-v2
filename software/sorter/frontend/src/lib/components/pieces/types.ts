// Shared shapes for the piece-detail panels. They live in their own module
// rather than in the components because `PieceThumbGrid` declares a generic,
// and a `generics` script can't also export types.

export type InfoRow = {
	label: string;
	value: string;
	mono?: boolean;
	valueClass?: string;
};

// One tile in a PieceThumbGrid. `ref` keeps the caller's own record so the
// grid's `overlay` snippet can render badges off the original data.
export type Thumb<R> = {
	key: string;
	src: string;
	alt?: string;
	title?: string;
	used?: boolean;
	caption?: string;
	captionRight?: string;
	ref: R;
};

// One frame the camera took of a piece, as the piece's page lays them out
// (FrameStrip): what to show, and what to say about it under the pointer.
export type Frame = {
	key: string;
	src: string;
	// Under the enlarged picture: which frame, when, and whether it was used.
	label: string;
	// It produced the applied result.
	used: boolean;
	// The channel it came from ("C4"), or "—" when that was never recorded.
	channel: string;
	// How sharp it is, when it was measured (higher is sharper).
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

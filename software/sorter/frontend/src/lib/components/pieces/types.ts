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

// Mirrors backend `format_track_label` (vision/overlays/tracker.py): Knuth
// multiplicative hash, then reduce into 4 base36 chars (~1.68M codes). This is
// the short id printed on the tracker overlay and on bin labels — the single
// source of truth for user-facing track identifiers.
const ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz';
const LABEL_LENGTH = 4;
const MODULO = ALPHABET.length ** LABEL_LENGTH;

export function formatTrackLabel(globalId: number | null | undefined): string | null {
	if (typeof globalId !== 'number' || !Number.isFinite(globalId)) return null;
	const mixed = (globalId * 2654435761) >>> 0;
	let value = mixed % MODULO;
	let result = '';
	for (let i = 0; i < LABEL_LENGTH; i++) {
		result = ALPHABET[value % ALPHABET.length] + result;
		value = Math.floor(value / ALPHABET.length);
	}
	return result;
}

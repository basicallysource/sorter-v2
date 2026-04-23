// Mirrors backend `format_track_label` (vision/overlays/tracker.py): Knuth
// multiplicative hash mod 10000, zero-padded. This is the short id printed on
// the tracker overlay and on the bin labels — the single source of truth for
// user-facing track identifiers.
export function formatTrackLabel(globalId: number | null | undefined): string | null {
	if (typeof globalId !== 'number' || !Number.isFinite(globalId)) return null;
	const mixed = (globalId * 2654435761) >>> 0;
	return (mixed % 10000).toString().padStart(4, '0');
}

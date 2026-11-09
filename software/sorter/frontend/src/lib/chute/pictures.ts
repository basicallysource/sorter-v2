// The pictures of each kind of chute, by the kind's key
// (backend subsystems/distribution/chute_variants.py). Diagrams in light grey
// with the part that tells the kinds apart in orange, on a transparent
// background, so they read on a surface or a well in either mode. A machine
// with no internet shows none, and every page that uses them must read
// without them.

export type ChutePictures = {
	// A close-up of the part that tells the kinds apart: the one to choose by.
	closeUp: string;
	// Where that part sits on the whole chute.
	context: string;
};

const PICTURES: Record<string, ChutePictures> = {
	cable_cage: {
		closeUp: 'https://assets.basically.website/sorter-ui/chute-cable-cage-4bf6338ecc0c.webp',
		context: 'https://assets.basically.website/sorter-ui/chute-cable-cage-context-6c28ae28a543.webp'
	},
	slip_ring: {
		closeUp: 'https://assets.basically.website/sorter-ui/chute-slip-ring-4c9ea54c4b14.webp',
		context: 'https://assets.basically.website/sorter-ui/chute-slip-ring-context-a5df421635c0.webp'
	}
};

export function chutePictures(key: string | null | undefined): ChutePictures | null {
	return (key && PICTURES[key]) || null;
}

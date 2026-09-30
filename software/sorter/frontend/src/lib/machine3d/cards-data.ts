// What each bin's card says, from the layout, the sorting profile's category
// names and, for the styles that show them, the pieces that went in last.
import { categoryLabel } from '$lib/components/bins/pieces';
import type { BinPlace } from './layout';
import type { CardData } from './cards';

/** The pieces that went into a bin last, newest first: colour and picture. */
export type RecentPiece = { color: string | null; image: string | null };
export type Recent = Map<string, RecentPiece[]>;

type ContentsBin = {
	bin_key: string;
	recent_pieces?: { color_id?: string | null; brickognize_preview_url?: string | null }[];
};

/** The recent pieces of every bin (GET /api/bins/contents), with each piece's
 *  colour from the BrickLink palette (GET /api/pieces/colors). */
export async function loadRecent(base: string, palette: Map<string, string>): Promise<Recent> {
	const res = await fetch(`${base}/api/bins/contents`);
	if (!res.ok) throw new Error(`/api/bins/contents: HTTP ${res.status}`);
	const data = (await res.json()) as { bins: ContentsBin[] };
	const recent: Recent = new Map();
	for (const b of data.bins ?? [])
		recent.set(
			b.bin_key,
			(b.recent_pieces ?? []).map((p) => ({
				color: (p.color_id && palette.get(String(p.color_id))) || null,
				image: p.brickognize_preview_url ?? null
			}))
		);
	return recent;
}

export function cardsFor(
	places: BinPlace[],
	recent: Recent | null,
	images: Map<string, CanvasImageSource> = new Map()
): CardData[] {
	return places.map((p) => {
		const pieces = recent?.get(p.key) ?? [];
		return {
			name: categoryLabel(p.categoryIds),
			code: `Layer ${p.layer + 1} · Bin ${p.globalIndex + 1}`,
			number: String(p.globalIndex + 1),
			colors: pieces.map((r) => r.color).filter((c): c is string => !!c),
			images: pieces.map((r) => (r.image ? (images.get(r.image) ?? null) : null))
		};
	});
}

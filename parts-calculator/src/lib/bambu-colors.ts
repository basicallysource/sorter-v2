/**
 * Bambu Lab PLA Matte color palette — names + hex from Bambu's official
 * PLA Matte hex-code table. Used by the filament color pickers so choices map to
 * actual orderable Bambu filament.
 */
export type BambuColor = { id: string; name: string; hex: string };

export const DEFAULT_COLOR_ID = 'charcoal';

export const BAMBU_COLORS: readonly BambuColor[] = [
	// whites / tans / browns
	{ id: 'ivory-white', name: 'Ivory White', hex: '#FFFFFF' },
	{ id: 'bone-white', name: 'Bone White', hex: '#CBC6B8' },
	{ id: 'desert-tan', name: 'Desert Tan', hex: '#E8DBB7' },
	{ id: 'latte-brown', name: 'Latte Brown', hex: '#D3B7A7' },
	{ id: 'caramel', name: 'Caramel', hex: '#AE835B' },
	{ id: 'terracotta', name: 'Terracotta', hex: '#B15533' },
	{ id: 'dark-brown', name: 'Dark Brown', hex: '#7D6556' },
	{ id: 'dark-chocolate', name: 'Dark Chocolate', hex: '#4D3324' },
	// purples / pinks / orange / yellow
	{ id: 'lilac-purple', name: 'Lilac Purple', hex: '#AE96D4' },
	{ id: 'sakura-pink', name: 'Sakura Pink', hex: '#E8AFCF' },
	{ id: 'mandarin-orange', name: 'Mandarin Orange', hex: '#F99963' },
	{ id: 'lemon-yellow', name: 'Lemon Yellow', hex: '#F7D959' },
	{ id: 'plum', name: 'Plum', hex: '#950051' },
	// reds / greens
	{ id: 'scarlet-red', name: 'Scarlet Red', hex: '#DE4343' },
	{ id: 'dark-red', name: 'Dark Red', hex: '#BB3D43' },
	{ id: 'dark-green', name: 'Dark Green', hex: '#68724D' },
	{ id: 'grass-green', name: 'Grass Green', hex: '#61C680' },
	{ id: 'apple-green', name: 'Apple Green', hex: '#C2E189' },
	// blues
	{ id: 'ice-blue', name: 'Ice Blue', hex: '#A3D8E1' },
	{ id: 'sky-blue', name: 'Sky Blue', hex: '#56B7E6' },
	{ id: 'marine-blue', name: 'Marine Blue', hex: '#0078BF' },
	{ id: 'dark-blue', name: 'Dark Blue', hex: '#042F56' },
	// grays / black
	{ id: 'ash-gray', name: 'Ash Gray', hex: '#9B9EA0' },
	{ id: 'nardo-gray', name: 'Nardo Gray', hex: '#757575' },
	{ id: 'charcoal', name: 'Charcoal', hex: '#000000' }
];

export function getBambuColor(id: string | null | undefined): BambuColor {
	if (typeof id === 'string') {
		const found = BAMBU_COLORS.find((c) => c.id === id);
		if (found) return found;
	}
	return BAMBU_COLORS.find((c) => c.id === DEFAULT_COLOR_ID)!;
}

/**
 * Bambu Lab PLA Matte color palette — names + hex from Bambu's official
 * PLA Matte hex-code table. Used by the filament color pickers so choices map to
 * actual orderable Bambu filament.
 *
 * `lego` is the nearest LEGO color, in BrickLink naming, for people who know
 * "light bluish gray" but not "Ash Gray". It is only set where the match is a
 * real one: nearest BrickLink solid color by CIEDE2000 over the two hexes, kept
 * only at dE <= 6, which is close enough that the two read as the same color.
 * A filament with no close LEGO counterpart (Plum, Scarlet Red, Marine Blue,
 * Bone White...) has no `lego` and shows nothing, rather than a misleading
 * "closest". Charcoal is the one hand-set entry: pure #000000 against LEGO
 * Black #05131D computes as dE 7.9 because dE is exaggerated at the black end,
 * and in filament it is simply black.
 */
export type BambuColor = {
	id: string;
	name: string;
	hex: string;
	/** nearest LEGO color in BrickLink naming, only where it is a real match */
	lego?: { name: string; hex: string; de: number };
};

export const DEFAULT_COLOR_ID = 'charcoal';

export const BAMBU_COLORS: readonly BambuColor[] = [
	// whites / tans / browns
	{ id: 'ivory-white', name: 'Ivory White', hex: '#FFFFFF', lego: { name: 'White', hex: '#FFFFFF', de: 0.0 } },
	{ id: 'bone-white', name: 'Bone White', hex: '#CBC6B8' },
	{ id: 'desert-tan', name: 'Desert Tan', hex: '#E8DBB7', lego: { name: 'Tan', hex: '#E4CD9E', de: 5.1 } },
	{ id: 'latte-brown', name: 'Latte Brown', hex: '#D3B7A7' },
	{ id: 'caramel', name: 'Caramel', hex: '#AE835B', lego: { name: 'Medium Nougat', hex: '#AA7D55', de: 2.0 } },
	{ id: 'terracotta', name: 'Terracotta', hex: '#B15533', lego: { name: 'Dark Nougat', hex: '#AD6140', de: 3.8 } },
	{ id: 'dark-brown', name: 'Dark Brown', hex: '#7D6556', lego: { name: 'Medium Brown', hex: '#755945', de: 4.8 } },
	{ id: 'dark-chocolate', name: 'Dark Chocolate', hex: '#4D3324', lego: { name: 'Brown', hex: '#583927', de: 3.0 } },
	// purples / pinks / orange / yellow
	{ id: 'lilac-purple', name: 'Lilac Purple', hex: '#AE96D4' },
	{ id: 'sakura-pink', name: 'Sakura Pink', hex: '#E8AFCF', lego: { name: 'Bright Pink', hex: '#E4ADC8', de: 1.6 } },
	{ id: 'mandarin-orange', name: 'Mandarin Orange', hex: '#F99963' },
	{ id: 'lemon-yellow', name: 'Lemon Yellow', hex: '#F7D959', lego: { name: 'Yellow', hex: '#F2CD37', de: 3.6 } },
	{ id: 'plum', name: 'Plum', hex: '#950051' },
	// reds / greens
	{ id: 'scarlet-red', name: 'Scarlet Red', hex: '#DE4343' },
	{ id: 'dark-red', name: 'Dark Red', hex: '#BB3D43' },
	{ id: 'dark-green', name: 'Dark Green', hex: '#68724D' },
	{ id: 'grass-green', name: 'Grass Green', hex: '#61C680' },
	{ id: 'apple-green', name: 'Apple Green', hex: '#C2E189', lego: { name: 'Yellowish Green', hex: '#DFEEA5', de: 5.5 } },
	// blues
	{ id: 'ice-blue', name: 'Ice Blue', hex: '#A3D8E1' },
	{ id: 'sky-blue', name: 'Sky Blue', hex: '#56B7E6', lego: { name: 'Sky Blue', hex: '#7DBFDD', de: 5.1 } },
	{ id: 'marine-blue', name: 'Marine Blue', hex: '#0078BF' },
	{ id: 'dark-blue', name: 'Dark Blue', hex: '#042F56', lego: { name: 'Dark Blue', hex: '#0A3463', de: 2.3 } },
	// grays / black
	{ id: 'ash-gray', name: 'Ash Gray', hex: '#9B9EA0', lego: { name: 'Light Bluish Gray', hex: '#A0A5A9', de: 2.4 } },
	{ id: 'nardo-gray', name: 'Nardo Gray', hex: '#757575', lego: { name: 'Dark Bluish Gray', hex: '#6C6E68', de: 5.0 } },
	{ id: 'charcoal', name: 'Charcoal', hex: '#000000', lego: { name: 'Black', hex: '#05131D', de: 0 } }
];

export function getBambuColor(id: string | null | undefined): BambuColor {
	if (typeof id === 'string') {
		const found = BAMBU_COLORS.find((c) => c.id === id);
		if (found) return found;
	}
	return BAMBU_COLORS.find((c) => c.id === DEFAULT_COLOR_ID)!;
}

// What a bin is named by. The backend (bin_key.py) writes it into a bin's
// category_ids: a plain profile category id ("bricks"), or, when the machine
// sorts by part or color, a key that lists what it is made of
// ("part:3001", "color:5", "category:bricks|color:5").

export const BIN_KEY_COMPONENTS = ['category', 'part', 'color'] as const;
export type BinKeyComponent = (typeof BIN_KEY_COMPONENTS)[number];

export const BIN_KEY_LABELS: Record<BinKeyComponent, string> = {
	category: 'Category',
	part: 'Part',
	color: 'Color'
};

export type BinKeyParts = Partial<Record<BinKeyComponent, string>>;

// The pieces of a key, or null for a plain category id.
export function parseBinKey(key: string | null | undefined): BinKeyParts | null {
	if (!key || !BIN_KEY_COMPONENTS.some((component) => key.startsWith(`${component}:`))) return null;
	const parts: BinKeyParts = {};
	for (const token of key.split('|')) {
		const at = token.indexOf(':');
		if (at < 0) continue;
		const name = token.slice(0, at) as BinKeyComponent;
		const value = token.slice(at + 1);
		if (BIN_KEY_COMPONENTS.includes(name) && value) parts[name] = value;
	}
	return Object.keys(parts).length > 0 ? parts : null;
}

// The components in key order, whichever order they came in; the default
// (category) when nothing valid is left.
export function normalizeSortBy(raw: unknown): BinKeyComponent[] {
	const wanted = Array.isArray(raw) ? raw : [];
	const picked = BIN_KEY_COMPONENTS.filter((component) => wanted.includes(component));
	return picked.length > 0 ? picked : ['category'];
}

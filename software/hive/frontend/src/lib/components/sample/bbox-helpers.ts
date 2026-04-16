export type Bbox = { x: number; y: number; w: number; h: number };
export type PaletteColor = { stroke: string; fill: string };

export const proposalPalette: readonly PaletteColor[] = [
	{ stroke: '#22c55e', fill: 'rgba(34, 197, 94, 0.10)' },
	{ stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.10)' },
	{ stroke: '#f97316', fill: 'rgba(249, 115, 22, 0.10)' },
	{ stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.10)' },
	{ stroke: '#eab308', fill: 'rgba(234, 179, 8, 0.10)' },
	{ stroke: '#ef4444', fill: 'rgba(239, 68, 68, 0.10)' }
] as const;

export function proposalColor(index: number): PaletteColor {
	return proposalPalette[index % proposalPalette.length];
}

export function parseBbox(b: unknown): Bbox | null {
	if (Array.isArray(b) && b.length >= 4) {
		const [x1, y1, x2, y2] = b;
		if ([x1, y1, x2, y2].every((value) => typeof value === 'number')) {
			return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
		}
	}
	if (
		b &&
		typeof b === 'object' &&
		'x' in b &&
		'y' in b &&
		'w' in b &&
		'h' in b &&
		typeof (b as { x: unknown }).x === 'number' &&
		typeof (b as { y: unknown }).y === 'number' &&
		typeof (b as { w: unknown }).w === 'number' &&
		typeof (b as { h: unknown }).h === 'number'
	) {
		const obj = b as Bbox;
		return { x: obj.x, y: obj.y, w: obj.w, h: obj.h };
	}
	return null;
}

export function parseBboxCollection(raw: unknown): Bbox[] {
	if (Array.isArray(raw)) {
		if (raw.length >= 4 && typeof raw[0] === 'number') {
			const single = parseBbox(raw);
			return single ? [single] : [];
		}
		return raw.map(parseBbox).filter((bbox): bbox is Bbox => bbox !== null);
	}
	if (raw && typeof raw === 'object') {
		const single = parseBbox(raw);
		return single ? [single] : [];
	}
	return [];
}

export function extractPrimaryBboxes(
	detectionBboxes: unknown,
	extraDetectionBbox: unknown
): Bbox[] {
	const direct = parseBboxCollection(detectionBboxes);
	return direct.length > 0 ? direct : parseBboxCollection(extraDetectionBbox);
}

export function extractLegacyReviewBboxes(extraReview: unknown): Bbox[] {
	if (!extraReview || typeof extraReview !== 'object') return [];
	const corrections = (extraReview as Record<string, unknown>).box_corrections;
	if (!Array.isArray(corrections)) return [];
	return corrections
		.map((entry) => {
			if (!entry || typeof entry !== 'object') return null;
			return parseBbox((entry as Record<string, unknown>).bbox);
		})
		.filter((bbox): bbox is Bbox => bbox !== null);
}


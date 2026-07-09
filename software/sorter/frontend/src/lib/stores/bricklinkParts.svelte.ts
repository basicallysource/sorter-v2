import type { components } from '$lib/api/rest';

type BricklinkPartResponse = components['schemas']['BricklinkPartResponse'];

// Shared cache of BrickLink part lookups, keyed by part_id. The backend proxies
// the (slow) BrickLink API, so each part is fetched once per app session no
// matter how many cards or modals render it.
let cache = $state<Map<string, BricklinkPartResponse | null>>(new Map());

export const bricklinkParts = {
	get(partId: string | null | undefined): BricklinkPartResponse | null {
		if (!partId) return null;
		return cache.get(partId) ?? null;
	},
	async fetch(baseUrl: string, partId: string): Promise<void> {
		if (cache.has(partId)) return;
		cache = new Map(cache).set(partId, null);
		try {
			const res = await fetch(`${baseUrl}/bricklink/part/${encodeURIComponent(partId)}`);
			if (res.ok) {
				cache = new Map(cache).set(partId, await res.json());
			}
		} catch {
			// ignore lookup errors
		}
	}
};

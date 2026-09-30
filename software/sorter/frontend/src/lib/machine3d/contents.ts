// The pieces that went into each bin last, for the cards on the bins. The
// contents carry pictures and are heavy, so they are fetched only when the
// backend's change token (GET /api/bins/contents/version) moves, as the Bins
// page does.
import type { BinContentItem, BinContents } from '$lib/components/bins/types';

/** Each bin's most recent pieces, newest first, by bin key. */
export type Recent = Record<string, BinContentItem[]>;

export function watchContents(base: string, pieces: number, onChange: (recent: Recent) => void) {
	let version: string | null = null;
	let loaded = false;
	let busy = false;

	/** Reads the token, and the contents if it moved (or was never read). */
	async function check() {
		if (busy) return;
		busy = true;
		try {
			const res = await fetch(`${base}/api/bins/contents/version`);
			const next = res.ok ? ((await res.json()) as { version?: unknown }).version : null;
			const token = typeof next === 'string' ? next : null;
			if (loaded && (token === null || token === version)) return;
			const contents = await fetch(`${base}/api/bins/contents`);
			if (!contents.ok) return;
			const data = (await contents.json()) as { bins?: BinContents[] };
			const recent: Recent = {};
			for (const b of data.bins ?? []) recent[b.bin_key] = (b.recent_pieces ?? []).slice(0, pieces);
			version = token;
			loaded = true;
			onChange(recent);
		} catch {
			// The cards keep what they showed; the next check tries again.
		} finally {
			busy = false;
		}
	}

	return { check };
}

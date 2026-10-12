/**
 * The last Wi-Fi and Tailscale status each machine reported, kept for as long
 * as the app is open, so Settings > Networking shows them at once and
 * refreshes them behind the scenes instead of opening on a spinner.
 */

const last = new Map<string, { value: unknown; at: number }>();

export function remembered<T>(key: string): T | null {
	return (last.get(key)?.value as T | undefined) ?? null;
}

/** How long ago `key` was remembered, in milliseconds; Infinity if never. */
export function age(key: string): number {
	const entry = last.get(key);
	return entry ? Date.now() - entry.at : Infinity;
}

export function remember<T>(key: string, value: T): T {
	last.set(key, { value, at: Date.now() });
	return value;
}

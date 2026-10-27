/**
 * The last Wi-Fi and Tailscale status each machine reported, kept for as long
 * as the app is open, so Settings > Networking shows them at once and
 * refreshes them behind the scenes instead of opening on a spinner.
 */

const last = new Map<string, unknown>();

export function remembered<T>(key: string): T | null {
	return (last.get(key) as T | undefined) ?? null;
}

export function remember<T>(key: string, value: T): T {
	last.set(key, value);
	return value;
}

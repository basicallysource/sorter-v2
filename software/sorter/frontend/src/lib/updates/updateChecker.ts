/**
 * Background software-update checker.
 *
 * Every few minutes we ask the backend (with `refresh=true`, which does a real
 * `git fetch`) whether the ref this machine is currently on — branch or tag —
 * has moved on origin. The backend already computes this per available version:
 * the entry with `is_current: true` and `up_to_date: false` means "you are behind
 * the thing you're tracking". When that's the case we raise a green
 * "Update available" notification linking to the Versions page.
 *
 * The notification id encodes the target sha, so a *newer* update re-notifies
 * even if the user dismissed an earlier one, while re-checking the same target
 * every interval does not resurface a dismissed notification.
 */

import { Download } from 'lucide-svelte';
import { getBackendHttpBase } from '$lib/backend';
import { notifications } from '$lib/stores/notifications.svelte';

const UPDATE_ID_PREFIX = 'update:';
const DEFAULT_INTERVAL_MS = 5 * 60 * 1000;

type VersionEntry = {
	kind: 'branch' | 'tag';
	channel?: string;
	name: string;
	sha: string;
	is_current: boolean;
	up_to_date: boolean;
};

async function checkForUpdates(): Promise<void> {
	if (typeof window === 'undefined') return;
	try {
		const res = await fetch(`${getBackendHttpBase()}/api/system/versions?refresh=true`);
		if (!res.ok) return;
		const data = (await res.json()) as { available?: VersionEntry[] };
		const current = (data.available ?? []).find((e) => e.is_current);

		if (current && !current.up_to_date) {
			// Single update notification reflecting the latest target sha.
			notifications.removeByPrefix(UPDATE_ID_PREFIX);
			const label = current.channel ? `${current.channel} ${current.name}` : current.name;
			notifications.push({
				id: `${UPDATE_ID_PREFIX}${current.kind}:${current.name}:${current.sha}`,
				title: 'Update available',
				content: `${label} → ${current.sha}`,
				icon: Download,
				color: 'success',
				href: '/settings/versions'
			});
		} else {
			// On this ref and up to date (or nothing current) — clear any stale one.
			notifications.removeByPrefix(UPDATE_ID_PREFIX);
		}
	} catch {
		// Network hiccup — leave any existing notification as-is.
	}
}

export function startUpdateChecker(intervalMs: number = DEFAULT_INTERVAL_MS): () => void {
	if (typeof window === 'undefined') return () => {};
	void checkForUpdates();
	const timer = window.setInterval(() => void checkForUpdates(), intervalMs);
	return () => window.clearInterval(timer);
}

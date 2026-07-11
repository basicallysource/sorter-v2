/**
 * App-wide notification store.
 *
 * Notifications are keyed by a stable `id`. Dismissing one records the id in
 * `userConfig` (persisted), so it never shows again — even across reloads or a
 * re-`push` of the same id. To make a notification re-appear after some change
 * (e.g. a newer software version), give it an id that encodes that change so the
 * new id is not in the dismissed set.
 *
 * The top-bar indicator renders `notifications.active`.
 */

import { Bell } from 'lucide-svelte';
import { userConfig } from './userConfig.svelte';

// Matches the repo convention for lucide icon props (see settings/stations.ts).
export type LucideIcon = typeof Bell;

export type NotificationColor = 'success' | 'primary' | 'warning' | 'danger';

export interface AppNotification {
	id: string;
	title: string;
	content?: string;
	icon?: LucideIcon;
	color: NotificationColor;
	/** If set, clicking the notification navigates here. */
	href?: string;
}

let items = $state<AppNotification[]>([]);

export const notifications = {
	get active(): AppNotification[] {
		return items.filter((n) => !userConfig.isDismissed(n.id));
	},

	push(n: AppNotification): void {
		if (userConfig.isDismissed(n.id)) return;
		const idx = items.findIndex((x) => x.id === n.id);
		if (idx >= 0) {
			items[idx] = n;
		} else {
			items = [...items, n];
		}
	},

	/** Remove a notification from the list without marking it dismissed. */
	remove(id: string): void {
		items = items.filter((n) => n.id !== id);
	},

	removeByPrefix(prefix: string): void {
		items = items.filter((n) => !n.id.startsWith(prefix));
	},

	/** User closed it — hide now and remember so it stays hidden. */
	dismiss(id: string): void {
		userConfig.dismiss(id);
		items = items.filter((n) => n.id !== id);
	}
};

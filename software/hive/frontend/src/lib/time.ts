/** Shared time formatting. Hive's UI copy is English — keep it that way.
 *
 * Locale-sensitive calls pass an explicit `en-US` rather than `undefined`, so
 * the output does not change with whatever locale the viewer's browser reports.
 * The wording matches the Sorter's own relative-age formatter
 * (`HiveModelsSection.svelte`) so the same model reads identically on both.
 */

/** "just now" / "3 hours ago" / "2 weeks ago", falling back to a date past ~5 weeks. */
export function relativeTime(iso: string): string {
	const then = new Date(iso).getTime();
	if (!Number.isFinite(then)) return '';
	const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
	if (sec < 60) return 'just now';
	const min = Math.round(sec / 60);
	if (min < 60) return `${min} min ago`;
	const hr = Math.round(min / 60);
	if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`;
	const days = Math.round(hr / 24);
	if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`;
	const weeks = Math.round(days / 7);
	if (weeks < 5) return `${weeks} week${weeks === 1 ? '' : 's'} ago`;
	return formatDate(iso);
}

/** "Aug 9, 2026". */
export function formatDate(iso: string): string {
	return new Date(iso).toLocaleDateString('en-US', {
		year: 'numeric',
		month: 'short',
		day: 'numeric'
	});
}

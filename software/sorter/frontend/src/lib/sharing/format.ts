// How the Data pages write sizes, counts and times.

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

// "0 B", "812 KB", "1.5 GB"
export function formatBytes(bytes: number | null | undefined): string {
	if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return '0 B';
	const i = Math.max(0, Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1));
	const value = bytes / 1024 ** i;
	// One decimal under 100, and not a trailing ".0": "5 MB", "5.4 MB", "812 KB".
	return `${Number(value.toFixed(i === 0 || value >= 100 ? 0 : 1))} ${UNITS[i]}`;
}

// "3,200"
export function formatCount(count: number): string {
	return Math.round(count).toLocaleString();
}

// "just now", "5 min ago", "3 h ago", "2 days ago"
export function formatAgo(seconds: number): string {
	const s = Math.max(0, Math.round(seconds));
	if (s < 60) return 'just now';
	const min = Math.round(s / 60);
	if (min < 60) return `${min} min ago`;
	const hours = Math.round(min / 60);
	if (hours < 48) return `${hours} h ago`;
	return `${Math.round(hours / 24)} days ago`;
}

// "40 s", "8 min", "1.5 h"
export function formatWait(seconds: number): string {
	const s = Math.max(0, seconds);
	if (s < 1) return '0 s';
	if (s < 60) return `${Math.round(s)} s`;
	if (s < 3600) return `${Math.round(s / 60)} min`;
	return `${(Math.round((s / 3600) * 10) / 10).toLocaleString()} h`;
}

// "3 pm"
export function formatHour(ts: number): string {
	return new Date(ts * 1000).toLocaleTimeString('en-US', { hour: 'numeric' }).toLowerCase();
}

// "Mon 3 pm"
export function formatDayHour(ts: number): string {
	const day = new Date(ts * 1000).toLocaleDateString('en-US', { weekday: 'short' });
	return `${day} ${formatHour(ts)}`;
}

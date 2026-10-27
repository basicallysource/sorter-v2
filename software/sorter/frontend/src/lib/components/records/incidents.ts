// What the incidents views read from the machine (GET /api/incidents and
// /api/incidents/summary), and how a row's facts are written.

export type KindSummary = {
	kind: string;
	count: number;
	avg_duration_s: number | null;
	operator_resolved: number;
	auto_resolved: number;
};

export type IncidentsSummary = {
	total: number;
	active: number;
	by_kind: KindSummary[];
	by_day: { date: string; count: number }[];
	by_channel: { channel: string; count: number }[];
};

export type IncidentRow = {
	id: number;
	kind: string;
	channel: string | null;
	channel_label: string | null;
	severity: string | null;
	reason: string | null;
	operator_message: string | null;
	status: string;
	triggered_at: number;
	resolved_at: number | null;
	resolved_by: string | null;
	duration_s: number | null;
};

// "exit_stuck" reads "Exit stuck": sentence case, like every other label.
export function formatKind(kind: string): string {
	const words = kind.replace(/_/g, ' ');
	return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatDuration(seconds: number | null): string {
	if (seconds == null || seconds < 0) return '—';
	if (seconds < 60) return `${Math.round(seconds)}s`;
	const minutes = Math.floor(seconds / 60);
	const secs = Math.round(seconds % 60);
	if (minutes < 60) return `${minutes}m ${secs}s`;
	const hours = Math.floor(minutes / 60);
	return `${hours}h ${minutes % 60}m`;
}

export function formatTimestamp(ts: number): string {
	return new Date(ts * 1000).toLocaleString(undefined, {
		month: 'short',
		day: 'numeric',
		hour: 'numeric',
		minute: '2-digit'
	});
}

export function resolvedByLabel(value: string | null): string {
	if (value === 'operator') return 'Operator';
	if (value === 'superseded') return 'Superseded';
	if (value === 'auto' || value === 'system') return 'Auto';
	return '—';
}

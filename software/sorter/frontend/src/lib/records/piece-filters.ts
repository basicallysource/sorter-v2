// What the Pieces view can be filtered by. The address holds the filters under
// short names that read well (?status=classified&from=2026-10-01); the machine
// is asked under its own (status, dead, date_from, ...). `toPieceQuery` is the
// one place that turns one into the other.

export const pieceFilterKeys = [
	'q',
	'status',
	'run',
	'lot',
	'bin',
	'from',
	'to',
	'reviewed',
	'sort'
] as const;

export const statusOptions = [
	{ value: '', label: 'Any status' },
	{ value: 'classified', label: 'Classified' },
	{ value: 'unidentified', label: 'Unidentified' },
	{ value: 'failed', label: 'ID failed' },
	{ value: 'multi_drop', label: 'Multi drop' },
	{ value: 'timed_out', label: 'Timed out' }
];

export const reviewedOptions = [
	{ value: '', label: 'Any review' },
	{ value: 'yes', label: 'Reviewed' },
	{ value: 'no', label: 'Not reviewed' }
];

export const sortOptions = [
	{ value: '', label: 'Newest first' },
	{ value: 'oldest', label: 'Oldest first' }
];

// What each status is, to the machine. A timed-out piece is a flag, not a status.
const STATUS: Record<string, Record<string, string>> = {
	classified: { status: 'classified' },
	unidentified: { status: 'unknown,not_found' },
	failed: { status: 'failed' },
	multi_drop: { status: 'multi_drop_fail' },
	timed_out: { dead: 'true' }
};

// A day in the address ("2026-10-01") as the machine's clock sees it: the first
// moment of that day in this browser's time zone, or the last.
function dayEdge(day: string | undefined, end: boolean): string | null {
	const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day ?? '');
	if (!match) return null;
	const [year, month, date] = [Number(match[1]), Number(match[2]), Number(match[3])];
	const at = end
		? new Date(year, month - 1, date, 23, 59, 59, 999)
		: new Date(year, month - 1, date);
	return Number.isNaN(at.getTime()) ? null : String(at.getTime() / 1000);
}

export function toPieceQuery(filters: Record<string, string>): Record<string, string> {
	const query: Record<string, string> = {};
	if (filters.q) query.q = filters.q;
	Object.assign(query, STATUS[filters.status] ?? {});
	if (filters.run) query.sorting_run_id = filters.run;
	else if (filters.lot) query.lot_id = filters.lot;
	// A run's piece count leaves out the pieces reaped as stuck, so its list does
	// too, and the two agree: the "Timed out" status is how to see them.
	if ((filters.run || filters.lot) && query.dead === undefined) query.dead = 'false';
	const bin = (filters.bin ?? '').split('-').map(Number);
	if (bin.length === 3 && bin.every((n) => Number.isInteger(n) && n >= 0)) {
		[query.bin_x, query.bin_y, query.bin_z] = bin.map(String);
	}
	const from = dayEdge(filters.from, false);
	if (from) query.date_from = from;
	const to = dayEdge(filters.to, true);
	if (to) query.date_to = to;
	if (filters.reviewed === 'yes') query.reviewed = 'true';
	if (filters.reviewed === 'no') query.reviewed = 'false';
	if (filters.sort === 'oldest') query.sort = 'oldest';
	return query;
}

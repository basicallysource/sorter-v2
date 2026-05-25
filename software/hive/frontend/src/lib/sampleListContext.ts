export const SAMPLE_LIST_DEFAULT_PAGE_SIZE = 30;

// 'scope' is included so the URL ?scope=mine survives reloads and is carried back to the list
// from sample detail. Default scope (omitted) is "all samples". 'max_age_hours' carries the
// Age sidebar filter (24/168/720) so reload preserves it.
export const SAMPLE_LIST_FILTER_KEYS = [
	'scope',
	'machine_id',
	'review_status',
	'source_role',
	'capture_reason',
	'kind',
	'my_review',
	'annotated',
	'exposure',
	'archived',
	'max_age_hours'
] as const;

export type SampleListFilterKey = (typeof SAMPLE_LIST_FILTER_KEYS)[number];

const SAMPLE_LIST_CONTEXT_KEYS = [
	...SAMPLE_LIST_FILTER_KEYS,
	'page',
	'page_size'
] as const;

export interface SampleListFilters {
	scope?: string;
	machine_id?: string;
	review_status?: string;
	source_role?: string;
	capture_reason?: string;
	// 'regular' | 'condition' | undefined (= all). Coarser than capture_reason
	// — splits the queue between detection samples and condition-collector
	// crops so reviewers / browsers can drain one bucket at a time.
	kind?: string;
	// Per-user review filter: 'unreviewed' (viewer hasn't reviewed yet),
	// 'reviewed' (viewer reviewed either way), 'accepted', 'rejected'.
	// Independent of the global review_status — that's the consensus state
	// across all reviewers, this is "what did *I* do".
	my_review?: string;
	// Filter by whether a Hive teacher (Gemini/Perceptron) has already
	// processed the sample. 'teacher' = re-run done (training-ready);
	// 'raw' = still raw sorter detections, often incomplete.
	annotated?: string;
	// Histogram-based exposure bucket: 'under' / 'normal' / 'over' / 'all'.
	// Useful for catching lights-off batches or sensor saturation. Null/''
	// means no filter (sees both clean and broken-exposure samples).
	exposure?: string;
	// Admin-only: 'active' (default), 'archived' (only archived), 'all'. Members
	// always see 'active' regardless of what they pass — server enforces.
	archived?: string;
	max_age_hours?: string;
}

export interface SampleListContext extends SampleListFilters {
	page: number;
	page_size: number;
}

function parsePositiveInt(raw: string | null, fallback: number): number {
	if (raw == null) return fallback;
	const value = Number(raw);
	if (!Number.isFinite(value) || value < 1) return fallback;
	return Math.floor(value);
}

export function readSampleListContext(searchParams: URLSearchParams): SampleListContext {
	const ctx: SampleListContext = {
		page: parsePositiveInt(searchParams.get('page'), 1),
		page_size: parsePositiveInt(searchParams.get('page_size'), SAMPLE_LIST_DEFAULT_PAGE_SIZE)
	};
	for (const key of SAMPLE_LIST_FILTER_KEYS) {
		const value = searchParams.get(key);
		if (value) ctx[key] = value;
	}
	return ctx;
}

export function sampleListContextQuery(searchParams: URLSearchParams): string {
	const sp = new URLSearchParams();
	for (const key of SAMPLE_LIST_CONTEXT_KEYS) {
		const value = searchParams.get(key);
		if (value) sp.set(key, value);
	}
	const search = sp.toString();
	return search ? `?${search}` : '';
}

export function sampleListFilterParams(ctx: SampleListContext): SampleListFilters {
	const out: SampleListFilters = {};
	for (const key of SAMPLE_LIST_FILTER_KEYS) {
		const value = ctx[key];
		if (value) out[key] = value;
	}
	return out;
}

export function sampleListContextKey(ctx: SampleListContext): string {
	return JSON.stringify({
		scope: ctx.scope ?? '',
		machine_id: ctx.machine_id ?? '',
		review_status: ctx.review_status ?? '',
		source_role: ctx.source_role ?? '',
		capture_reason: ctx.capture_reason ?? '',
		kind: ctx.kind ?? '',
		my_review: ctx.my_review ?? '',
		annotated: ctx.annotated ?? '',
		exposure: ctx.exposure ?? '',
		archived: ctx.archived ?? '',
		max_age_hours: ctx.max_age_hours ?? '',
		page_size: ctx.page_size
	});
}

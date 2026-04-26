export const SAMPLE_LIST_DEFAULT_PAGE_SIZE = 30;

export const SAMPLE_LIST_FILTER_KEYS = [
	'machine_id',
	'review_status',
	'source_role',
	'capture_reason'
] as const;

export type SampleListFilterKey = (typeof SAMPLE_LIST_FILTER_KEYS)[number];

const SAMPLE_LIST_CONTEXT_KEYS = [
	...SAMPLE_LIST_FILTER_KEYS,
	'page',
	'page_size'
] as const;

export interface SampleListFilters {
	machine_id?: string;
	review_status?: string;
	source_role?: string;
	capture_reason?: string;
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
		machine_id: ctx.machine_id ?? '',
		review_status: ctx.review_status ?? '',
		source_role: ctx.source_role ?? '',
		capture_reason: ctx.capture_reason ?? '',
		page_size: ctx.page_size
	});
}

// The Channel samples list: its filters in the URL, and the queue the grid, the
// sample detail page and the review page step through (lib/reviewQueue).
//
// The filters travel in the URL from the list to a sample and to the review
// page, so a reload or a shared link shows the same slice, and next / previous
// walk the same list the grid showed.

import { api, type Sample, type SampleFilterParams } from '$lib/api';
import { queueFor, readMachines, writeMachines, type ReviewQueue } from '$lib/reviewQueue.svelte';

// Filter keys carried in the URL besides the machine filter (lib/reviewQueue's
// `machine`). 'scope' is "mine" or absent (all samples).
export const SAMPLE_LIST_FILTER_KEYS = [
	'scope',
	'review_status',
	'source_role',
	'capture_reason',
	'kind',
	'my_review',
	'annotated',
	'exposure',
	'palette',
	'archived',
	'max_age_hours'
] as const;

export type SampleListFilterKey = (typeof SAMPLE_LIST_FILTER_KEYS)[number];

export type SampleListFilters = Partial<Record<SampleListFilterKey, string>> & { machine_ids: string[] };

export function readSampleFilters(sp: URLSearchParams): SampleListFilters {
	const out: SampleListFilters = { machine_ids: readMachines(sp) };
	for (const key of SAMPLE_LIST_FILTER_KEYS) {
		const value = sp.get(key);
		if (value) out[key] = value;
	}
	return out;
}

// Just the filters of a URL, as a query string (with its "?"), for a link that
// carries the slice along: the list to a sample, the list to the review page.
export function sampleFiltersQuery(sp: URLSearchParams): string {
	const out = new URLSearchParams();
	for (const key of SAMPLE_LIST_FILTER_KEYS) {
		const value = sp.get(key);
		if (value) out.set(key, value);
	}
	writeMachines(out, readMachines(sp));
	const qs = out.toString();
	return qs ? `?${qs}` : '';
}

export function sampleFiltersKey(f: SampleListFilters): string {
	const parts = SAMPLE_LIST_FILTER_KEYS.map((k) => `${k}=${f[k] ?? ''}`);
	return [...parts, `machine=${[...f.machine_ids].sort().join(',')}`].join('&');
}

export function sampleFilterParams(f: SampleListFilters): SampleFilterParams {
	const { machine_ids, ...rest } = f;
	return { ...rest, machine_ids };
}

// The review queue's slice: with no review state chosen it is the fresh work,
// samples I have not reviewed that still need reviews. Choosing a review state
// (say, conflicts, or what I accepted) revisits that state instead.
export function reviewFilterParams(f: SampleListFilters): SampleFilterParams {
	const params = sampleFilterParams(f);
	return f.review_status || f.my_review ? params : { ...params, needs_review: true };
}

function queue(list: string, key: string, params: SampleFilterParams): ReviewQueue<Sample> {
	return queueFor<Sample>(list, key, {
		key: (s) => s.id,
		fetch: (cursor) => api.getSamples({ ...params, cursor, limit: 60 })
	});
}

// The list the grid and the sample detail page share.
export function sampleQueue(f: SampleListFilters): ReviewQueue<Sample> {
	return queue('samples', sampleFiltersKey(f), sampleFilterParams(f));
}

// The list the review page steps through.
export function reviewQueue(f: SampleListFilters): ReviewQueue<Sample> {
	return queue('review', sampleFiltersKey(f), reviewFilterParams(f));
}

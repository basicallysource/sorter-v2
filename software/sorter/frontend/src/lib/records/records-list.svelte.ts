import { untrack } from 'svelte';
import { goto } from '$app/navigation';
import { page } from '$app/state';

// A long, newest-first list read from the machine a page at a time (the Pieces
// and Incidents views), kept still while the machine goes on adding to it.
//
// The address is the list's state: its filters, the page, and the anchor (the
// newest id the list was cut at when the search began), so Back, Forward and a
// reload show the same list. A fresh search has no anchor; the first answer
// names it, and it is put in the address from then on. Everything after the
// anchor is "newer": counted, never mixed into the pages.
//
// Pages are read by keyset: the next page starts after the last id of the one
// before it, so an item changed while someone pages (a piece reviewed, with a
// "not reviewed" filter on) never makes the next page skip or repeat one. That
// needs the cursors of pages already read, kept here; a page jumped to, or
// restored from the address, is read by its offset from the anchor instead.
// A machine that does not name an anchor is an older one: its list walks one
// page at a time, and cannot jump.

type ListResponse<T> = {
	items: T[];
	next_cursor: string | null;
	total: number;
	anchor?: number | null;
	newer?: number | null;
};

export type RecordsListOptions = {
	// The machine's address, and the path the list is read from.
	base: () => string;
	path: string;
	pageSize: number;
	// The address's query keys that are filters; the rest is ignored.
	filters: readonly string[];
	// How the filters in the address are asked of the machine, when they are
	// not asked under the same names (a day in the address is a time to it).
	toQuery?: (filters: Record<string, string>) => Record<string, string>;
};

const NEWER_POLL_MS = 20_000;

export class RecordsList<T> {
	items = $state<T[]>([]);
	total = $state(0);
	// How many arrived after the anchor, or null when this machine does not say.
	newer = $state<number | null>(null);
	loading = $state(true);
	failed = $state(false);
	// The page shown, counted from 0.
	pageIndex = $state(0);
	// False for a machine that cannot read a page by its offset.
	canJump = $state(false);
	// Bumped when a page someone asked for has arrived (not on the first
	// load), so the view can bring its top into sight.
	turned = $state(0);

	// How many a page holds: what was asked for, or fewer when the machine cannot
	// give that many (an older one caps a page), so the pages are numbered by
	// what they hold.
	#served = $state(0);
	#opts: RecordsListOptions;
	#path: string;
	// The anchor, as a value that effects can depend on.
	#anchorState = $state<number | null>(null);
	#cursors = new Map<number, string>();
	// What the listing now held is: its filters and its anchor. The pages of one
	// listing share their cursors; another listing starts over.
	#search: string | null = null;
	#key: string | null = null;
	#controller: AbortController | null = null;
	#asked = false;

	constructor(opts: RecordsListOptions) {
		this.#opts = opts;
		this.#served = opts.pageSize;
		this.#path = page.url.pathname;

		// The address drives the list. Only while it is this view's own address:
		// leaving the view changes the address before the view is gone.
		$effect(() => {
			const url = page.url;
			if (url.pathname !== this.#path) return;
			const key = this.#keyOf(url);
			untrack(() => {
				if (key !== this.#key) void this.#load(url, key);
			});
		});

		// What arrived since, without reading a page.
		$effect(() => {
			if (this.#anchorState == null) return;
			const id = setInterval(() => {
				if (!document.hidden) void this.#countNewer();
			}, NEWER_POLL_MS);
			return () => clearInterval(id);
		});

		$effect(() => () => this.#controller?.abort());
	}

	get pageSize(): number {
		return this.#served;
	}
	get pageCount(): number {
		return Math.max(1, Math.ceil(this.total / this.pageSize));
	}
	get from(): number {
		return this.items.length === 0 ? 0 : this.pageIndex * this.pageSize + 1;
	}
	get to(): number {
		return this.pageIndex * this.pageSize + this.items.length;
	}
	// The filters now in the address.
	get filters(): Record<string, string> {
		const out: Record<string, string> = {};
		if (page.url.pathname !== this.#path) return out;
		for (const key of this.#opts.filters) {
			const value = page.url.searchParams.get(key);
			if (value) out[key] = value;
		}
		return out;
	}
	// The query that names this listing, for something that must match it (an export).
	get query(): URLSearchParams {
		const params = new URLSearchParams(this.#asQuery(this.filters));
		if (this.#anchorState != null) params.set('anchor', String(this.#anchorState));
		return params;
	}

	#asQuery(filters: Record<string, string>): Record<string, string> {
		return this.#opts.toQuery ? this.#opts.toQuery(filters) : filters;
	}

	#searchOf(url: URL): string {
		const parts = this.#opts.filters.map((k) => `${k}=${url.searchParams.get(k) ?? ''}`);
		parts.push(`anchor=${url.searchParams.get('anchor') ?? ''}`);
		return parts.join('&');
	}

	#keyOf(url: URL): string {
		return `${this.#searchOf(url)}&page=${url.searchParams.get('page') ?? ''}`;
	}

	// Change the filters: a new search, from the newest.
	setFilters(patch: Record<string, string | null>): void {
		const url = new URL(page.url);
		for (const [key, value] of Object.entries(patch)) {
			if (value) url.searchParams.set(key, value);
			else url.searchParams.delete(key);
		}
		url.searchParams.delete('anchor');
		url.searchParams.delete('page');
		void goto(url, { replaceState: true, keepFocus: true, noScroll: true });
	}

	// A new search with the same filters: everything that arrived is in.
	refresh(): void {
		const url = new URL(page.url);
		if (url.searchParams.has('anchor') || url.searchParams.has('page')) this.setFilters({});
		else this.reload();
	}

	// Ask the machine again for what is on the address now (after a failure).
	reload(): void {
		const url = new URL(page.url);
		this.#key = null;
		this.#search = null;
		untrack(() => void this.#load(url, this.#keyOf(url)));
	}

	// Another page of this listing (counted from 0); it becomes a history entry.
	open(pageIndex: number): void {
		const url = new URL(page.url);
		if (pageIndex > 0) url.searchParams.set('page', String(pageIndex + 1));
		else url.searchParams.delete('page');
		this.#asked = true;
		void goto(url, { keepFocus: true, noScroll: true });
	}

	#params(url: URL, pageIndex: number): URLSearchParams {
		const filters: Record<string, string> = {};
		for (const key of this.#opts.filters) {
			const value = url.searchParams.get(key);
			if (value) filters[key] = value;
		}
		const params = new URLSearchParams(this.#asQuery(filters));
		params.set('limit', String(this.#opts.pageSize));
		const anchor = url.searchParams.get('anchor');
		if (anchor) params.set('anchor', anchor);
		if (pageIndex > 0) {
			const cursor = this.#cursors.get(pageIndex);
			if (cursor) params.set('cursor', cursor);
			else params.set('offset', String(pageIndex * this.#served));
		}
		return params;
	}

	async #load(url: URL, key: string): Promise<void> {
		const wanted = Math.max(0, (Number(url.searchParams.get('page')) || 1) - 1);
		const fresh = !url.searchParams.get('anchor');
		if (this.#searchOf(url) !== this.#search) this.#cursors.clear();
		this.#key = key;
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		this.loading = true;
		try {
			const res = await fetch(
				`${this.#opts.base()}${this.#opts.path}?${this.#params(url, wanted)}`,
				{ signal: controller.signal }
			);
			if (!res.ok) throw new Error(`${res.status}`);
			const json = (await res.json()) as ListResponse<T>;
			if (controller.signal.aborted) return;

			this.canJump = json.anchor != null;
			const items = Array.isArray(json.items) ? json.items : [];
			if (json.next_cursor && items.length > 0 && items.length < this.#opts.pageSize) {
				this.#served = items.length;
			}
			// A machine that cannot read by offset answered the first page.
			const shown = this.canJump || this.#cursors.has(wanted) ? wanted : 0;
			this.items = items;
			this.total = typeof json.total === 'number' ? json.total : 0;
			this.newer = typeof json.newer === 'number' ? json.newer : null;
			this.pageIndex = shown;
			if (json.next_cursor) this.#cursors.set(shown + 1, json.next_cursor);
			else this.#cursors.delete(shown + 1);
			this.#anchorState = json.anchor ?? null;
			this.failed = false;
			if (this.#asked) {
				this.#asked = false;
				this.turned += 1;
			}

			// Put what names this listing in the address, once (no new history
			// entry); and past the end (a stale address) go to the last page there is.
			const next = new URL(url);
			if (json.anchor != null && fresh) next.searchParams.set('anchor', String(json.anchor));
			if (shown === 0) next.searchParams.delete('page');
			const pastEnd = this.items.length === 0 && this.total > 0 && shown > 0;
			if (pastEnd) next.searchParams.set('page', String(this.pageCount));
			const nextKey = this.#keyOf(next);
			this.#search = this.#searchOf(next);
			if (nextKey !== key) {
				// A page past the end is loaded again from its new address.
				if (!pastEnd) this.#key = nextKey;
				void goto(next, { replaceState: true, keepFocus: true, noScroll: true });
			}
		} catch (error) {
			if (controller.signal.aborted) return;
			this.failed = true;
			this.#key = null;
			console.error('[RecordsList]', this.#opts.path, error);
		} finally {
			if (this.#controller === controller) this.loading = false;
		}
	}

	async #countNewer(): Promise<void> {
		if (this.#anchorState == null || this.loading) return;
		const params = new URLSearchParams(this.#asQuery(this.filters));
		params.set('limit', '0');
		params.set('anchor', String(this.#anchorState));
		try {
			const res = await fetch(`${this.#opts.base()}${this.#opts.path}?${params}`);
			if (!res.ok) return;
			const json = (await res.json()) as ListResponse<T>;
			if (typeof json.newer === 'number') this.newer = json.newer;
		} catch {
			// the next poll tries again
		}
	}
}

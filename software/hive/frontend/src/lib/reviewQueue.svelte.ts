// The list behind a review page: the grid, "load more", and next / previous in
// the panel or detail page all read one queue, so they agree on the order and
// on what the filters let through.
//
// A queue belongs to one set of filters. Changing a filter makes a new queue,
// and the old one is dropped: an answer still on its way for the old filters
// lands in the dropped queue and is never shown. (Appending such a late answer
// to the current list is how one machine's pieces once showed up in another
// machine's grid.)

export type QueuePage<T> = { items: T[]; next_cursor: string | null };

export type QueueSource<T> = {
	// A stable id for an item: the list never holds the same item twice.
	key: (item: T) => string;
	// The page after `cursor` (null for the first page).
	fetch: (cursor: string | null) => Promise<QueuePage<T>>;
};

function message(e: unknown): string {
	return e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to load the list';
}

export class ReviewQueue<T> {
	items = $state<T[]>([]);
	hasMore = $state(true);
	loading = $state(false);
	loadingMore = $state(false);
	error = $state<string | null>(null);
	// Which filters this queue is for.
	readonly filtersKey: string;

	#source: QueueSource<T>;
	#cursor: string | null = null;
	#seen = new Set<string>();
	#generation = 0;
	#inflight: Promise<boolean> | null = null;
	#started = false;

	constructor(filtersKey: string, source: QueueSource<T>) {
		this.filtersKey = filtersKey;
		this.#source = source;
	}

	key(item: T): string {
		return this.#source.key(item);
	}

	// Load the first page unless that already happened (a queue is shared by
	// every view of the same list, so the second view finds it loaded).
	start(): Promise<void> {
		if (this.#started) return Promise.resolve();
		return this.reload();
	}

	// Start the list over. Anything still on its way is dropped.
	async reload(): Promise<void> {
		this.#started = true;
		const generation = ++this.#generation;
		this.items = [];
		this.#seen = new Set();
		this.#cursor = null;
		this.#inflight = null;
		this.hasMore = true;
		this.error = null;
		this.loading = true;
		this.loadingMore = false;
		try {
			const page = await this.#source.fetch(null);
			if (generation === this.#generation) this.#take(page);
		} catch (e) {
			if (generation === this.#generation) this.error = message(e);
		} finally {
			if (generation === this.#generation) this.loading = false;
		}
	}

	// Stop taking answers: for a queue its page has left.
	drop(): void {
		this.#generation++;
	}

	// The next page. One request at a time; resolves true when it added items.
	loadMore(): Promise<boolean> {
		if (this.#inflight) return this.#inflight;
		if (!this.hasMore || this.loading) return Promise.resolve(false);
		const generation = this.#generation;
		this.loadingMore = true;
		const run = (async () => {
			try {
				const page = await this.#source.fetch(this.#cursor);
				if (generation !== this.#generation) return false;
				return this.#take(page) > 0;
			} catch (e) {
				if (generation === this.#generation) {
					this.error = message(e);
					this.hasMore = false;
				}
				return false;
			} finally {
				if (generation === this.#generation) {
					this.loadingMore = false;
					this.#inflight = null;
				}
			}
		})();
		this.#inflight = run;
		return run;
	}

	#take(page: QueuePage<T>): number {
		const fresh = page.items.filter((it) => !this.#seen.has(this.key(it)));
		for (const it of fresh) this.#seen.add(this.key(it));
		this.items = [...this.items, ...fresh];
		this.#cursor = page.next_cursor;
		this.hasMore = page.next_cursor != null;
		return fresh.length;
	}

	indexOf(key: string): number {
		return this.items.findIndex((it) => this.key(it) === key);
	}

	// The item after `key`, loading pages as needed; the first item when `key`
	// is not in the list; null at the end.
	async after(key: string): Promise<T | null> {
		const i = this.indexOf(key);
		if (i < 0) return this.items[0] ?? null;
		while (i + 1 >= this.items.length && this.hasMore) {
			const added = await this.loadMore();
			if (!added && !this.hasMore) break;
			if (!added && this.error) break;
		}
		return this.items[i + 1] ?? null;
	}

	before(key: string): T | null {
		const i = this.indexOf(key);
		return i > 0 ? this.items[i - 1] : null;
	}

	// Load pages until `key` is in the list (a detail page opened from a link),
	// up to `maxPages`. Returns its index, or -1.
	async find(key: string, maxPages = 10): Promise<number> {
		await this.start();
		let i = this.indexOf(key);
		for (let n = 0; i < 0 && this.hasMore && n < maxPages; n++) {
			await this.loadMore();
			i = this.indexOf(key);
		}
		return i;
	}

	position(key: string): { index: number; total: number; hasMore: boolean } {
		return { index: this.indexOf(key), total: this.items.length, hasMore: this.hasMore };
	}

	// Change one item in place (a label just saved), without a reload.
	patch(key: string, change: (item: T) => T): void {
		this.items = this.items.map((it) => (this.key(it) === key ? change(it) : it));
	}
}

// What a detail page needs to step through a queue, whatever its items are.
export interface QueueSteps {
	readonly items: { id: string }[];
	readonly hasMore: boolean;
	indexOf(key: string): number;
	after(key: string): Promise<{ id: string } | null>;
	find(key: string, maxPages?: number): Promise<number>;
}

// One queue per list for the session, so the grid and the detail page of the
// same list share it. Asking for other filters drops the old queue.
const queues = new Map<string, ReviewQueue<unknown>>();

export function queueFor<T>(list: string, filtersKey: string, source: QueueSource<T>): ReviewQueue<T> {
	const current = queues.get(list) as ReviewQueue<T> | undefined;
	if (current && current.filtersKey === filtersKey) return current;
	current?.drop();
	const next = new ReviewQueue<T>(filtersKey, source);
	queues.set(list, next as ReviewQueue<unknown>);
	return next;
}

// ArrowLeft / ArrowRight step through a queue, unless the key is meant for a
// field, or a modifier is down. Returns true when it handled the key.
export function queueKeydown(e: KeyboardEvent, step: { prev?: () => void; next?: () => void }): boolean {
	if (e.metaKey || e.ctrlKey || e.altKey) return false;
	const target = e.target as HTMLElement | null;
	if (target) {
		const tag = target.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable) return false;
	}
	if (e.key === 'ArrowLeft' && step.prev) {
		e.preventDefault();
		step.prev();
		return true;
	}
	if (e.key === 'ArrowRight' && step.next) {
		e.preventDefault();
		step.next();
		return true;
	}
	return false;
}

// The machine filter in a URL: `machine=<id>,<id>`. Several machines or one;
// none means every machine the viewer may see.
export function readMachines(sp: URLSearchParams): string[] {
	const raw = [...sp.getAll('machine'), ...sp.getAll('machine_id')].flatMap((v) => v.split(','));
	return [...new Set(raw.map((v) => v.trim()).filter(Boolean))];
}

export function writeMachines(sp: URLSearchParams, ids: string[]): void {
	sp.delete('machine');
	sp.delete('machine_id');
	if (ids.length > 0) sp.set('machine', ids.join(','));
}

import { untrack } from 'svelte';
import { fetchPieceImageState, type ImageState } from '$lib/components/records/piece-images';

// The pictures of the pieces on the page. They load a few at a time instead of
// firing a request for every piece at once; pieces that leave the page stop
// loading (and are forgotten), and the ones on it load top to bottom.
const CONCURRENCY = 6;

type Candidate = { uuid: string; seen_at: number | null };

export class ImageHydrator {
	states = $state<Record<string, ImageState>>({});

	#base: () => string;
	#wanted = new Set<string>();
	#queue: Candidate[] = [];
	#workers = 0;

	constructor(base: () => string) {
		this.#base = base;
	}

	// The pieces now on the page: load the ones not loaded, forget the rest.
	show(pieces: Candidate[]): void {
		// Called from an effect: reading and writing the states here must not make
		// that effect depend on them.
		untrack(() => {
			this.#wanted = new Set(pieces.map((p) => p.uuid));
			this.#queue = this.#queue.filter((c) => this.#wanted.has(c.uuid));
			const kept: Record<string, ImageState> = {};
			for (const [uuid, state] of Object.entries(this.states)) {
				if (this.#wanted.has(uuid)) kept[uuid] = state;
			}
			this.states = kept;
			for (const piece of pieces) {
				if (piece.uuid in this.states || this.#queue.some((c) => c.uuid === piece.uuid)) continue;
				this.#queue.push(piece);
			}
			while (this.#workers < CONCURRENCY && this.#queue.length > this.#workers) void this.#work();
		});
	}

	async #work(): Promise<void> {
		this.#workers += 1;
		try {
			for (let next = this.#queue.shift(); next; next = this.#queue.shift()) {
				if (!this.#wanted.has(next.uuid)) continue;
				this.states = { ...this.states, [next.uuid]: { status: 'loading', images: [] } };
				const result = await fetchPieceImageState(this.#base(), next.uuid, next.seen_at);
				if (!this.#wanted.has(next.uuid)) continue;
				this.states = { ...this.states, [next.uuid]: result };
			}
		} finally {
			this.#workers -= 1;
		}
	}
}

import { untrack } from 'svelte';
import { fetchPieceImageState, type ImageState } from '$lib/components/records/piece-images';

// The pictures of the pieces on the page, loaded for the ones near the screen.
// A page can hold a few hundred pieces and each needs a few requests, so a piece
// asks (`want`) when it comes near the window and says (`unwant`) when it
// leaves, before its turn if the reader has scrolled on: what is on the screen
// is what loads, a few at a time, never a request for every piece at once.
const CONCURRENCY = 6;

type Candidate = { uuid: string; seen_at: number | null };

export class ImageHydrator {
	states = $state<Record<string, ImageState>>({});

	#base: () => string;
	#queue: Candidate[] = [];
	#workers = 0;

	constructor(base: () => string) {
		this.#base = base;
	}

	// The pieces now on the page: forget the pictures of the rest.
	keepOnly(uuids: string[]): void {
		// Called from an effect: reading and writing the states here must not make
		// that effect depend on them.
		untrack(() => {
			const keep = new Set(uuids);
			this.#queue = this.#queue.filter((c) => keep.has(c.uuid));
			const kept: Record<string, ImageState> = {};
			for (const [uuid, state] of Object.entries(this.states)) {
				if (keep.has(uuid)) kept[uuid] = state;
			}
			if (Object.keys(kept).length !== Object.keys(this.states).length) this.states = kept;
		});
	}

	// A piece is near the screen: load its pictures, unless they are loaded or on the way.
	want(piece: Candidate): void {
		untrack(() => {
			if (piece.uuid in this.states || this.#queue.some((c) => c.uuid === piece.uuid)) return;
			this.#queue.push(piece);
			while (this.#workers < CONCURRENCY && this.#queue.length > this.#workers) void this.#work();
		});
	}

	// A piece left the screen: if its turn has not come, it no longer takes one.
	unwant(uuid: string): void {
		this.#queue = this.#queue.filter((c) => c.uuid !== uuid);
	}

	async #work(): Promise<void> {
		this.#workers += 1;
		try {
			for (let next = this.#queue.shift(); next; next = this.#queue.shift()) {
				this.states = { ...this.states, [next.uuid]: { status: 'loading', images: [] } };
				const result = await fetchPieceImageState(this.#base(), next.uuid, next.seen_at);
				// A piece that has left the page has no state to put it in.
				if (!(next.uuid in this.states)) continue;
				this.states = { ...this.states, [next.uuid]: result };
			}
		} finally {
			this.#workers -= 1;
		}
	}
}

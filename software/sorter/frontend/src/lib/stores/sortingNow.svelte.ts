// What a machine is sorting now: its current sorting run (which names the lot,
// and whether the run adds to it or puts its pieces through again) and its
// lots, as /api/sorting-runs/now answers. One copy per machine, shared by the
// top bar's lot menu, which changes it, and the dashboard's Lot tab.

export type SortingRun = {
	id: string;
	name: string;
	lot_id: string | null;
	lot_name: string | null;
	adds_to_lot: boolean;
	started_at: number;
	pieces: number;
};

export type Lot = {
	id: string;
	name: string;
	pieces: number;
	runs: number;
	passes: number;
};

export type SortingNow = { run: SortingRun | null; lots: Lot[] };

const byBase = $state<Record<string, SortingNow>>({});
const loadedAt = new Map<string, number>();
// Counted per machine, so an answer asked for before a change never lands on
// top of the change's own.
const asked = new Map<string, number>();

async function request(base: string, path: string, body?: unknown): Promise<unknown> {
	const res = await fetch(`${base}${path}`, {
		method: body === undefined ? 'GET' : 'POST',
		headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	const data = await res.json().catch(() => null);
	if (!res.ok) throw new Error(data?.detail ?? `HTTP ${res.status}`);
	return data;
}

async function now(base: string, body?: unknown): Promise<void> {
	const turn = (asked.get(base) ?? 0) + 1;
	asked.set(base, turn);
	const answer = (await request(base, '/api/sorting-runs/now', body)) as SortingNow;
	if (asked.get(base) !== turn) return;
	byBase[base] = answer;
	loadedAt.set(base, Date.now());
}

export const sortingNow = {
	// Null until the machine has answered once.
	for(base: string): SortingNow | null {
		return byBase[base] ?? null;
	},

	// Ask the machine again, unless it answered within `maxAgeMs`.
	async refresh(base: string, maxAgeMs = 0): Promise<void> {
		if (Date.now() - (loadedAt.get(base) ?? 0) < maxAgeMs) return;
		await now(base);
	},

	// Sort into `lotId` from now on (null: no lot), adding to it or not.
	async set(base: string, lotId: string | null, addsToLot: boolean): Promise<void> {
		await now(base, { lot_id: lotId, adds_to_lot: addsToLot });
	},

	async createLot(base: string, name: string): Promise<void> {
		const lot = (await request(base, '/api/lots', { name })) as Lot;
		await now(base, { lot_id: lot.id, adds_to_lot: true });
	}
};

// The setup page's side of the API in ../../../README.md. Every screen is
// rendered from `State`; the three POSTs only ask the Sorter to do something.

export type Software = {
	state: 'waiting' | 'installing' | 'ready' | 'failed';
	step: string | null;
	done: number;
	total: number;
};

export type Network = {
	kind: 'wifi' | 'ethernet';
	name: string;
	address: string;
	internet: boolean;
};

export type JoinReason = 'password' | 'not_found' | 'no_address' | 'timeout' | 'other';

export type Join = {
	ssid: string;
	state: 'joining' | 'joined' | 'failed';
	reason: JoinReason | null;
	detail: string | null;
	address: string | null;
	internet: boolean | null;
	source: 'phone' | 'setup_site';
	at: number;
};

export type ScannedNetwork = {
	ssid: string;
	signal: number;
	security: string;
	saved: boolean;
};

export type SorterEvent = { at: number; text: string };

export type State = {
	now: number;
	clock_ok: boolean;
	sorter: { name: string; mdns: string; software: Software };
	// null once it has closed. live_join is false on a radio that must leave the
	// air to join: the phone then loses this page until the join is over.
	setup_network: { ssid: string; live_join: boolean } | null;
	networks: Network[];
	cable: 'none' | 'plugged' | 'connected';
	join: Join | null;
	scan: { scanning: boolean; at: number; networks: ScannedNetwork[] };
	events: SorterEvent[];
};

export type JoinRequest = {
	ssid: string;
	password: string;
	hidden: boolean;
	timezone?: string;
	name?: string;
	rendezvous_id?: string;
};

/** Enterprise Wi-Fi signs in with a username, which this page can't do. */
export const isEnterprise = (n: ScannedNetwork) => n.security.includes('802.1X');
export const isOpen = (n: ScannedNetwork) => n.security.trim() === '';

// A request that hangs (the phone is between networks) must not stall the
// poll: give up and let the next one try.
const TIMEOUT_MS = 5000;

async function call(path: string, body?: unknown): Promise<Response> {
	const abort = new AbortController();
	const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
	try {
		return await fetch(path, {
			method: body === undefined ? 'GET' : 'POST',
			headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
			body: body === undefined ? undefined : JSON.stringify(body),
			cache: 'no-store',
			signal: abort.signal
		});
	} finally {
		clearTimeout(timer);
	}
}

/** Throws on anything but the Sorter's JSON: once the phone has left the
 *  setup network, the same URL can answer from somewhere else entirely. */
export async function getState(): Promise<State> {
	const res = await call('/api/state');
	if (!res.ok) throw new Error(`state ${res.status}`);
	const state = await res.json();
	if (typeof state?.now !== 'number' || !state.sorter) throw new Error('not the Sorter');
	return state as State;
}

/** POST, and turn a refusal into an Error carrying the Sorter's own words. */
async function post(path: string, body: unknown = {}): Promise<void> {
	let res: Response;
	try {
		res = await call(path, body);
	} catch {
		throw new Error("Couldn't reach the Sorter. Try again.");
	}
	if (res.ok) return;
	const detail = await res
		.json()
		.then((b) => (typeof b?.detail === 'string' ? b.detail : null))
		.catch(() => null);
	throw new Error(detail ?? `The Sorter answered ${res.status}. Try again.`);
}

export const startJoin = (req: JoinRequest) => post('/api/join', req);
export const startScan = () => post('/api/scan');
export const finish = () => post('/api/done');

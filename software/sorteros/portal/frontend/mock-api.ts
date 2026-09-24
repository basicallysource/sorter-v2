// `pnpm dev` only: answers the page's API (../README.md) from fixtures, so the
// page can be worked on without a Sorter. Never part of a build.
//
// Open the page with ?scenario=<name> to start that scenario over; it sticks
// (a cookie), so a plain reload of / carries on from where it is.
//
//   fresh               nothing saved, eight networks (one open, one enterprise)
//   failed-password     the last join had the wrong password
//   failed-not-found    the last join was for a network the Sorter can't see
//   joining             a join under way
//   joined              on HomeNet with internet, software ready
//   joined-no-internet  on HomeNet, which has no internet
//   online-by-cable     online by cable, nothing joined yet
//   installing          on HomeNet, installing the Sorter software
//
// A join is `joining` for 3 s, then fails with a wrong password if the
// password was "wrong-password", and joins otherwise. A scan takes 2 s.

import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';
import type { Join, JoinRequest, ScannedNetwork, State } from './src/lib/api';

const ADDRESS = '192.168.1.68';

const SCAN: ScannedNetwork[] = [
	{ ssid: 'HomeNet', signal: 82, security: 'WPA2', saved: false },
	{ ssid: 'Workshop', signal: 71, security: 'WPA2 WPA3', saved: false },
	{ ssid: 'Garage Guest', signal: 64, security: '', saved: false },
	{ ssid: 'Studio', signal: 58, security: 'WPA2', saved: false },
	{ ssid: 'CorpNet', signal: 50, security: 'WPA2 802.1X', saved: false },
	{ ssid: 'Neighbor', signal: 41, security: 'WPA2', saved: false },
	{ ssid: 'DIRECT-7F-Printer', signal: 30, security: 'WPA2', saved: false },
	{ ssid: 'Linksys', signal: 14, security: 'WPA1 WPA2', saved: false }
];

const seconds = () => Math.floor(Date.now() / 1000);

function fresh(t: number): State {
	return {
		now: t,
		clock_ok: false,
		sorter: {
			name: 'sorter',
			mdns: 'sorter.local',
			software: { state: 'waiting', step: null, done: 0, total: 11 }
		},
		setup_network: { ssid: 'SorterOS-Setup-ABCDEF' },
		networks: [],
		cable: 'none',
		join: null,
		scan: { scanning: false, at: t - 40, networks: SCAN.map((n) => ({ ...n })) },
		events: [
			{ at: t - 310, text: 'Started' },
			{ at: t - 300, text: 'No cable and no saved Wi-Fi: opened the setup network' },
			{ at: t - 40, text: 'Scanned: 8 networks' }
		]
	};
}

function joinOf(ssid: string, state: Join['state'], at: number): Join {
	return { ssid, state, reason: null, detail: null, address: null, internet: null, source: 'phone', at };
}

function fail(s: State, ssid: string, reason: Join['reason'], detail: string, at: number): State {
	s.join = { ...joinOf(ssid, 'failed', at), reason, detail };
	s.events.push({ at: at - 25, text: `Joining ${ssid}` }, { at, text: `Couldn't join ${ssid}: ${detail}` });
	return s;
}

function succeed(s: State, ssid: string, internet: boolean, at: number): State {
	s.join = { ...joinOf(ssid, 'joined', at), address: ADDRESS, internet };
	s.networks = [{ kind: 'wifi', name: ssid, address: ADDRESS, internet }];
	for (const n of s.scan.networks) if (n.ssid === ssid) n.saved = true;
	s.events.push(
		{ at: at - 12, text: `Joining ${ssid}` },
		{ at, text: `Joined ${ssid} at ${ADDRESS}` },
		{ at: at + 1, text: internet ? `Internet works through ${ssid}` : `No internet through ${ssid}` }
	);
	if (internet) s.clock_ok = true;
	return s;
}

const SCENARIOS: Record<string, (t: number) => State> = {
	fresh,
	'failed-password': (t) =>
		fail(fresh(t), 'HomeNet', 'password', 'Secrets were required, but not provided', t - 20),
	'failed-not-found': (t) =>
		fail(fresh(t), 'Barn', 'not_found', "No network with SSID 'Barn' found", t - 20),
	joining: (t) => {
		const s = fresh(t);
		s.join = joinOf('HomeNet', 'joining', t - 8);
		s.events.push({ at: t - 8, text: 'Joining HomeNet' });
		return s;
	},
	joined: (t) => {
		const s = succeed(fresh(t), 'HomeNet', true, t - 30);
		s.sorter.software = { state: 'ready', step: null, done: 11, total: 11 };
		return s;
	},
	'joined-no-internet': (t) => succeed(fresh(t), 'HomeNet', false, t - 30),
	'online-by-cable': (t) => {
		const s = fresh(t);
		s.clock_ok = true;
		s.cable = 'connected';
		s.networks = [{ kind: 'ethernet', name: 'Ethernet', address: '192.168.2.3', internet: true }];
		s.scan.networks[1].saved = true;
		s.sorter.software = { state: 'installing', step: 'Installing packages', done: 6, total: 11 };
		s.events.push({ at: t - 200, text: 'Cable connected: 192.168.2.3, internet works' });
		return s;
	},
	installing: (t) => {
		const s = succeed(fresh(t), 'HomeNet', true, t - 90);
		s.sorter.software = { state: 'installing', step: 'Installing packages', done: 2, total: 11 };
		s.events.push({ at: t - 80, text: 'Installing the Sorter software' });
		return s;
	}
};

type Mock = {
	state: State;
	/** A join under way: when it settles, and how. */
	settle: { at: number; ssid: string; wrong: boolean; name: string | null } | null;
	/** When the scan under way finishes. */
	scanDone: number | null;
};

const create = (scenario: string): Mock => ({
	state: SCENARIOS[scenario](seconds()),
	settle: null,
	scanDone: null
});

/** Bring the mock up to now: finish a join or a scan whose time has come. */
function advance(m: Mock): State {
	const s = m.state;
	const t = seconds();
	s.now = t;
	if (m.settle && Date.now() >= m.settle.at) {
		const { ssid, wrong, name } = m.settle;
		const t = Math.floor(m.settle.at / 1000);
		m.settle = null;
		if (wrong) {
			s.join = { ...joinOf(ssid, 'failed', t), reason: 'password', detail: 'Secrets were required, but not provided' };
			s.events.push({ at: t, text: `Couldn't join ${ssid}: wrong password` });
		} else {
			s.join = { ...joinOf(ssid, 'joined', t), address: ADDRESS, internet: true };
			s.networks = [...s.networks.filter((n) => n.kind !== 'wifi'), { kind: 'wifi', name: ssid, address: ADDRESS, internet: true }];
			for (const n of s.scan.networks) if (n.ssid === ssid) n.saved = true;
			s.events.push({ at: t, text: `Joined ${ssid} at ${ADDRESS}` });
			if (name) {
				s.sorter.name = name;
				s.sorter.mdns = `${name}.local`;
				s.events.push({ at: t, text: `Renamed to ${name}` });
			}
			if (s.sorter.software.state === 'waiting') {
				s.sorter.software = { state: 'installing', step: 'Cloning the Sorter software', done: 0, total: 11 };
			}
			s.clock_ok = true;
		}
	}
	if (m.scanDone && Date.now() >= m.scanDone) {
		m.scanDone = null;
		s.scan.scanning = false;
		s.scan.at = t;
		for (const n of s.scan.networks) n.signal = Math.max(5, Math.min(99, n.signal + Math.round(Math.random() * 10 - 5)));
		s.scan.networks.sort((a, b) => b.signal - a.signal);
		s.events.push({ at: t, text: `Scanned: ${s.scan.networks.length} networks` });
	}
	s.events = s.events.slice(-20);
	return s;
}

function join(m: Mock, body: Partial<JoinRequest>): [number, object] {
	const ssid = body.ssid ?? '';
	const password = body.password ?? '';
	if (!ssid.trim()) return [400, { detail: "Type the network's name." }];
	if (password && (password.length < 8 || password.length > 63)) {
		return [400, { detail: 'Wi-Fi passwords are 8 to 63 characters.' }];
	}
	if (m.state.scan.networks.find((n) => n.ssid === ssid)?.security.includes('802.1X')) {
		return [400, { detail: `${ssid} needs a username. Use a cable instead.` }];
	}
	const t = seconds();
	m.state.join = joinOf(ssid, 'joining', t);
	m.state.events.push({ at: t, text: `Joining ${ssid}` });
	m.settle = { at: Date.now() + 3000, ssid, wrong: password === 'wrong-password', name: body.name ?? null };
	return [202, { ok: true }];
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
	let text = '';
	for await (const chunk of req) text += chunk;
	try {
		return text ? JSON.parse(text) : {};
	} catch {
		return {};
	}
}

function send(res: ServerResponse, status: number, body: object) {
	res.statusCode = status;
	res.setHeader('Content-Type', 'application/json');
	res.setHeader('Cache-Control', 'no-store');
	res.end(JSON.stringify(body));
}

export function mockApi(): Plugin {
	const mocks = new Map<string, Mock>();
	return {
		name: 'sorter-setup-mock-api',
		apply: 'serve',
		configureServer(server) {
			server.middlewares.use(async (req, res, next) => {
				const url = new URL(req.url ?? '/', 'http://localhost');
				const asked = url.searchParams.get('scenario');
				if (asked !== null && !url.pathname.startsWith('/api/')) {
					const scenario = Object.hasOwn(SCENARIOS, asked) ? asked : 'fresh';
					if (scenario !== asked) {
						server.config.logger.warn(`no scenario "${asked}"; one of: ${Object.keys(SCENARIOS).join(', ')}`);
					}
					mocks.set(scenario, create(scenario));
					res.setHeader('Set-Cookie', `scenario=${scenario}; Path=/; SameSite=Lax`);
					return next();
				}
				if (!url.pathname.startsWith('/api/')) return next();

				const cookie = /(?:^|;\s*)scenario=([^;]+)/.exec(req.headers.cookie ?? '')?.[1];
				const scenario = cookie && Object.hasOwn(SCENARIOS, cookie) ? cookie : 'fresh';
				const m = mocks.get(scenario) ?? create(scenario);
				mocks.set(scenario, m);

				const route = `${req.method} ${url.pathname}`;
				if (route === 'GET /api/state') return send(res, 200, advance(m));
				if (route === 'POST /api/join') {
					const [status, body] = join(m, (await readJson(req)) as Partial<JoinRequest>);
					return send(res, status, body);
				}
				if (route === 'POST /api/scan') {
					m.state.scan.scanning = true;
					m.scanDone = Date.now() + 2000;
					return send(res, 202, { ok: true });
				}
				if (route === 'POST /api/done') {
					m.state.events.push({ at: seconds(), text: 'Closing the setup network' });
					return send(res, 202, { ok: true });
				}
				return send(res, 404, { detail: `no ${route} in the mock` });
			});
		}
	};
}

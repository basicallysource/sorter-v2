import { getBackendHttpBase } from '$lib/backend';
import type { ChannelZones } from './model';

export type FindReport = {
	center_score: number;
	rim_score: number;
	frames: number;
	notes: string[];
};

// What the machine has seen of its pieces while running (backend/zones/watch.py).
export type PieceWatch = {
	running: boolean;
	channels?: Record<
		string,
		{
			falls?: number;
			handoffs?: number;
			frames?: number;
			landing_delay_s?: { p50: number; p90: number };
		}
	>;
};

async function json<T>(res: Response): Promise<T> {
	if (!res.ok) {
		let detail = `${res.status}`;
		try {
			const body = await res.json();
			detail = body?.detail ?? detail;
		} catch {
			// The status is all there is.
		}
		throw new Error(detail);
	}
	return (await res.json()) as T;
}

export async function loadZones(): Promise<Record<number, ChannelZones | null>> {
	const body = await json<{ channels: Record<string, ChannelZones | null> }>(
		await fetch(`${getBackendHttpBase()}/api/zones`, { cache: 'no-store' })
	);
	return Object.fromEntries(Object.entries(body.channels).map(([k, v]) => [Number(k), v]));
}

export async function saveZones(zones: ChannelZones): Promise<ChannelZones> {
	const body = await json<{ zones: ChannelZones }>(
		await fetch(`${getBackendHttpBase()}/api/zones/${zones.channel}`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(zones)
		})
	);
	return body.zones;
}

export async function findZones(channel: number): Promise<{ zones: ChannelZones; report: FindReport }> {
	return json(await fetch(`${getBackendHttpBase()}/api/zones/${channel}/find`, { method: 'POST' }));
}

export async function defaultZones(channel: number): Promise<ChannelZones> {
	const body = await json<{ zones: ChannelZones }>(
		await fetch(`${getBackendHttpBase()}/api/zones/${channel}/default`, { cache: 'no-store' })
	);
	return body.zones;
}

export async function loadPieceWatch(): Promise<PieceWatch> {
	return json(await fetch(`${getBackendHttpBase()}/api/zones/watch`, { cache: 'no-store' }));
}

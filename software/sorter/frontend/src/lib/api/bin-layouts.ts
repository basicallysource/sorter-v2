export type BinLayoutRecord = {
	id: string;
	name: string;
	profile_id: string | null;
	profile_source: string | null;
	created_at: number;
	updated_at: number;
	is_active: boolean;
	dirty: boolean;
};

type JsonError = { detail?: string };

async function unwrap<T>(res: Response): Promise<T> {
	if (!res.ok) {
		const body = (await res.json().catch(() => null)) as JsonError | null;
		throw new Error(body?.detail ?? `HTTP ${res.status}`);
	}
	return (await res.json()) as T;
}

export async function fetchBinLayouts(
	baseUrl: string,
	profileId?: string | null
): Promise<{ ok: boolean; layouts: BinLayoutRecord[] }> {
	const url = new URL(`${baseUrl}/api/bin-layouts`);
	if (profileId) url.searchParams.set('profile_id', profileId);
	return unwrap(await fetch(url.toString()));
}

export async function fetchActiveBinLayout(
	baseUrl: string
): Promise<{ ok: boolean; active: BinLayoutRecord | null }> {
	return unwrap(await fetch(`${baseUrl}/api/bin-layouts/active`));
}

export async function applyBinLayout(
	baseUrl: string,
	id: string
): Promise<{ ok: boolean; restart_required: boolean; layout: BinLayoutRecord }> {
	return unwrap(await fetch(`${baseUrl}/api/bin-layouts/${id}/apply`, { method: 'POST' }));
}

export async function saveBinLayout(
	baseUrl: string,
	id: string
): Promise<{ ok: boolean; layout: BinLayoutRecord }> {
	return unwrap(await fetch(`${baseUrl}/api/bin-layouts/${id}/save`, { method: 'POST' }));
}

export async function createBinLayout(
	baseUrl: string,
	name: string,
	makeActive = false
): Promise<{ ok: boolean; layout: BinLayoutRecord }> {
	return unwrap(
		await fetch(`${baseUrl}/api/bin-layouts`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ name, make_active: makeActive })
		})
	);
}

export async function renameBinLayout(
	baseUrl: string,
	id: string,
	name: string
): Promise<{ ok: boolean; layout: BinLayoutRecord }> {
	return unwrap(
		await fetch(`${baseUrl}/api/bin-layouts/${id}/rename`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ name })
		})
	);
}

export async function deleteBinLayout(baseUrl: string, id: string): Promise<{ ok: boolean }> {
	return unwrap(await fetch(`${baseUrl}/api/bin-layouts/${id}`, { method: 'DELETE' }));
}

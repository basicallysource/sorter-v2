export type BsxFile = {
	filename: string;
	name: string;
	uploaded_at: string | null;
	num_lots: number | null;
	num_parts: number | null;
	num_unique_items: number | null;
	item_type_counts: Record<string, number> | null;
	is_active: boolean;
	error: string | null;
};

export type BsxLibrary = {
	files: BsxFile[];
	active_filename: string | null;
};

type JsonError = { detail?: string };

async function unwrap<T>(res: Response): Promise<T> {
	if (!res.ok) {
		const body = (await res.json().catch(() => null)) as JsonError | null;
		throw new Error(body?.detail ?? `HTTP ${res.status}`);
	}
	return (await res.json()) as T;
}

export async function fetchBsxLibrary(baseUrl: string): Promise<BsxLibrary> {
	return unwrap<BsxLibrary>(await fetch(`${baseUrl}/api/bsx`));
}

export async function uploadBsx(baseUrl: string, file: File, name: string): Promise<BsxFile> {
	// Raw body (not multipart) so the backend needs no python-multipart dep.
	const url = `${baseUrl}/api/bsx/upload?name=${encodeURIComponent(name)}`;
	return unwrap<BsxFile>(
		await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/xml' }, body: file })
	);
}

export async function activateBsx(baseUrl: string, filename: string): Promise<BsxLibrary> {
	return unwrap<BsxLibrary>(
		await fetch(`${baseUrl}/api/bsx/activate`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ filename })
		})
	);
}

export async function deactivateBsx(baseUrl: string): Promise<BsxLibrary> {
	return unwrap<BsxLibrary>(await fetch(`${baseUrl}/api/bsx/deactivate`, { method: 'POST' }));
}

export async function deleteBsx(baseUrl: string, filename: string): Promise<BsxLibrary> {
	return unwrap<BsxLibrary>(
		await fetch(`${baseUrl}/api/bsx/${encodeURIComponent(filename)}`, { method: 'DELETE' })
	);
}

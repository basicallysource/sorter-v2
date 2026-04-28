export * from './ws';
export type * from './events';

import { backendHttpBaseUrl } from '$lib/backend';

export type HiveTarget = { id: string; name: string; url: string };

export type HiveModelSummary = {
	id: string;
	owner_id?: string;
	slug: string;
	version: number;
	name: string;
	description: string | null;
	model_family: string;
	scopes: string[] | null;
	is_public: boolean;
	published_at: string;
	updated_at: string;
	variant_runtimes: string[];
	installed: boolean;
};

export type HiveModelVariant = {
	id: string;
	runtime: string;
	file_name: string;
	file_size: number;
	sha256: string;
	format_meta: Record<string, unknown> | null;
	uploaded_at: string;
};

export type HiveModelDetail = HiveModelSummary & {
	training_metadata: Record<string, unknown> | null;
	variants: HiveModelVariant[];
	recommended_runtime: string | null;
};

export type HiveModelsPage = {
	items: HiveModelSummary[];
	total: number;
	page: number;
	page_size: number;
	pages: number;
};

export type HiveInstalledModel = {
	local_id: string;
	target_id: string;
	model_id: string;
	variant_runtime: string;
	available_variant_runtimes?: string[];
	sha256: string;
	name: string;
	model_family: string;
	size_bytes: number;
	downloaded_at: string;
	path: string;
};

export type HiveDownloadStatus = 'queued' | 'downloading' | 'done' | 'failed';

export type HiveDownloadJob = {
	job_id: string;
	status: HiveDownloadStatus;
	target_id: string;
	model_id: string;
	variant_runtime: string;
	variant_id: string;
	file_name: string;
	total_bytes: number;
	progress_bytes: number;
	error: string | null;
	created_at: string;
	updated_at: string;
};

export type HiveDownloadsResponse = { jobs: HiveDownloadJob[] };

async function parseError(res: Response): Promise<string> {
	let bodyText = '';
	try {
		bodyText = await res.text();
	} catch {
		bodyText = '';
	}
	if (bodyText) {
		try {
			const data = JSON.parse(bodyText);
			if (data && typeof data === 'object' && 'detail' in data) {
				const detail = (data as { detail: unknown }).detail;
				if (typeof detail === 'string') return detail;
				return JSON.stringify(detail);
			}
		} catch {
			// not JSON
		}
		return bodyText;
	}
	return `HTTP ${res.status}`;
}

export async function fetchHiveTargets(): Promise<HiveTarget[]> {
	const res = await fetch(`${backendHttpBaseUrl}/api/hive/targets`);
	if (!res.ok) {
		const msg = await parseError(res);
		const err = new Error(msg) as Error & { status?: number };
		err.status = res.status;
		throw err;
	}
	const data = await res.json();
	return Array.isArray(data) ? (data as HiveTarget[]) : [];
}

export type FetchHiveModelsOptions = {
	targetId?: string | null;
	scope?: string;
	runtime?: string;
	family?: string;
	query?: string;
	page?: number;
	pageSize?: number;
};

export async function fetchHiveModels(
	opts: FetchHiveModelsOptions = {}
): Promise<HiveModelsPage> {
	const params = new URLSearchParams();
	if (opts.targetId) params.set('target_id', opts.targetId);
	if (opts.scope) params.set('scope', opts.scope);
	if (opts.runtime) params.set('runtime', opts.runtime);
	if (opts.family) params.set('family', opts.family);
	if (opts.query) params.set('q', opts.query);
	if (typeof opts.page === 'number' && Number.isFinite(opts.page)) {
		params.set('page', String(opts.page));
	}
	if (typeof opts.pageSize === 'number' && Number.isFinite(opts.pageSize)) {
		params.set('page_size', String(opts.pageSize));
	}
	const qs = params.toString();
	const res = await fetch(
		`${backendHttpBaseUrl}/api/hive/models${qs ? `?${qs}` : ''}`
	);
	if (!res.ok) throw new Error(await parseError(res));
	const data = await res.json();
	if (Array.isArray(data)) {
		return {
			items: data as HiveModelSummary[],
			total: data.length,
			page: 1,
			page_size: data.length,
			pages: 1
		};
	}
	return {
		items: Array.isArray(data?.items) ? (data.items as HiveModelSummary[]) : [],
		total: Number.isFinite(data?.total) ? Number(data.total) : 0,
		page: Number.isFinite(data?.page) ? Number(data.page) : 1,
		page_size: Number.isFinite(data?.page_size) ? Number(data.page_size) : 0,
		pages: Number.isFinite(data?.pages) ? Number(data.pages) : 1
	};
}

export async function fetchHiveModelDetail(
	modelId: string,
	targetId?: string | null
): Promise<HiveModelDetail> {
	const params = new URLSearchParams();
	if (targetId) params.set('target_id', targetId);
	const qs = params.toString();
	const res = await fetch(
		`${backendHttpBaseUrl}/api/hive/models/${encodeURIComponent(modelId)}${qs ? `?${qs}` : ''}`
	);
	if (!res.ok) throw new Error(await parseError(res));
	return (await res.json()) as HiveModelDetail;
}

export async function fetchInstalledHiveModels(): Promise<HiveInstalledModel[]> {
	const res = await fetch(`${backendHttpBaseUrl}/api/hive/models/installed`);
	if (!res.ok) throw new Error(await parseError(res));
	const data = await res.json();
	return Array.isArray(data) ? (data as HiveInstalledModel[]) : [];
}

export async function enqueueHiveModelDownload(
	modelId: string,
	options: { targetId?: string | null; variantRuntime?: string | null } = {}
): Promise<{ job_id: string }> {
	const params = new URLSearchParams();
	if (options.targetId) params.set('target_id', options.targetId);
	if (options.variantRuntime) params.set('variant_runtime', options.variantRuntime);
	const qs = params.toString();
	const res = await fetch(
		`${backendHttpBaseUrl}/api/hive/models/${encodeURIComponent(modelId)}/download${qs ? `?${qs}` : ''}`,
		{ method: 'POST' }
	);
	if (!res.ok) throw new Error(await parseError(res));
	return (await res.json()) as { job_id: string };
}

export async function fetchHiveDownloads(): Promise<HiveDownloadJob[]> {
	const res = await fetch(`${backendHttpBaseUrl}/api/hive/downloads`);
	if (!res.ok) throw new Error(await parseError(res));
	const data = (await res.json()) as HiveDownloadsResponse;
	return Array.isArray(data?.jobs) ? data.jobs : [];
}

export async function deleteInstalledHiveModel(localId: string): Promise<void> {
	const res = await fetch(
		`${backendHttpBaseUrl}/api/hive/models/installed/${encodeURIComponent(localId)}`,
		{ method: 'DELETE' }
	);
	if (!res.ok) throw new Error(await parseError(res));
}

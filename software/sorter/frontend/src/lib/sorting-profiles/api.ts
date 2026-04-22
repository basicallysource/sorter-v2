import type {
	HiveTargetLibrary,
	PendingProfileApply,
	SortingProfileDetail,
	SortingProfileLibraryResponse,
	SortingProfileSummary
} from './types';

type JsonError = { detail?: string };

async function unwrap<T>(res: Response): Promise<T> {
	if (!res.ok) {
		const body = (await res.json().catch(() => null)) as JsonError | null;
		throw new Error(body?.detail ?? `HTTP ${res.status}`);
	}
	return (await res.json()) as T;
}

export async function fetchLibrary(baseUrl: string): Promise<SortingProfileLibraryResponse> {
	const res = await fetch(`${baseUrl}/api/sorting-profiles/library`);
	return unwrap<SortingProfileLibraryResponse>(res);
}

export async function fetchProfileDetail(
	baseUrl: string,
	targetId: string,
	profileId: string,
	versionId?: string | null
): Promise<SortingProfileDetail> {
	const url = new URL(
		`${baseUrl}/api/sorting-profiles/targets/${encodeURIComponent(targetId)}/profiles/${encodeURIComponent(profileId)}`
	);
	if (versionId) url.searchParams.set('version_id', versionId);
	const res = await fetch(url.toString());
	return unwrap<SortingProfileDetail>(res);
}

export type ApplyProfileResponse = {
	activation_error?: string | null;
	[key: string]: unknown;
};

export async function applyProfile(
	baseUrl: string,
	request: PendingProfileApply
): Promise<ApplyProfileResponse> {
	const res = await fetch(`${baseUrl}/api/sorting-profiles/apply`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			target_id: request.target_id,
			profile_id: request.profile_id,
			profile_name: request.profile_name,
			version_id: request.version_id,
			version_number: request.version_number,
			version_label: request.version_label,
			reset_bin_categories: true
		})
	});
	return unwrap<ApplyProfileResponse>(res);
}

export async function reloadRuntimeProfile(baseUrl: string): Promise<void> {
	const res = await fetch(`${baseUrl}/api/sorting-profiles/reload`, { method: 'POST' });
	if (!res.ok) {
		const body = (await res.json().catch(() => null)) as JsonError | null;
		throw new Error(body?.detail ?? `HTTP ${res.status}`);
	}
}

// ─── Pure helpers (no I/O) ─────────────────────────────────────────────────

import type { SortingProfileVersionSummary } from './types';

export function visibleVersions(detail: SortingProfileDetail): SortingProfileVersionSummary[] {
	return detail.is_owner ? detail.versions : detail.versions.filter((v) => v.is_published);
}

export function displayVersion(profile: SortingProfileSummary): SortingProfileVersionSummary | null {
	return profile.latest_published_version ?? profile.latest_version;
}

export function targetWebUrl(target: HiveTargetLibrary): string | null {
	if (!target.url) return null;
	try {
		const url = new URL(target.url);
		if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
			url.pathname = url.pathname.replace(/^\/api(?=\/|$)/, '') || '/';
		}
		if ((url.hostname === 'localhost' || url.hostname === '127.0.0.1') && url.port === '8001') {
			url.port = '5174';
		}
		return url.toString();
	} catch {
		return target.url;
	}
}

export function sourceLabel(target: HiveTargetLibrary): string {
	return target.name || target.url || 'Unknown source';
}

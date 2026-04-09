export type RecentSortingProfileEntry = {
	target_id: string;
	target_name: string;
	profile_id: string;
	profile_name: string;
	version_id: string;
	version_number: number | null;
	version_label: string | null;
	last_used_at: string;
};

const MAX_RECENT_SORTING_PROFILES = 8;

function storageKey(machineKey: string): string {
	return `recent-sorting-profiles:${machineKey}`;
}

function isValidEntry(value: unknown): value is RecentSortingProfileEntry {
	if (!value || typeof value !== 'object') return false;
	const entry = value as Record<string, unknown>;
	return (
		typeof entry.target_id === 'string' &&
		typeof entry.target_name === 'string' &&
		typeof entry.profile_id === 'string' &&
		typeof entry.profile_name === 'string' &&
		typeof entry.version_id === 'string' &&
		(entry.version_number === null || typeof entry.version_number === 'number') &&
		(entry.version_label === null || typeof entry.version_label === 'string') &&
		typeof entry.last_used_at === 'string'
	);
}

function sameEntry(a: RecentSortingProfileEntry, b: RecentSortingProfileEntry): boolean {
	return a.target_id === b.target_id && a.profile_id === b.profile_id && a.version_id === b.version_id;
}

export function loadRecentSortingProfiles(machineKey: string | null | undefined): RecentSortingProfileEntry[] {
	if (typeof window === 'undefined' || !machineKey) return [];
	try {
		const raw = window.localStorage.getItem(storageKey(machineKey));
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) return [];
		return parsed.filter(isValidEntry).slice(0, MAX_RECENT_SORTING_PROFILES);
	} catch {
		return [];
	}
}

export function rememberRecentSortingProfile(
	machineKey: string | null | undefined,
	entry: Omit<RecentSortingProfileEntry, 'last_used_at'> & { last_used_at?: string | null }
): RecentSortingProfileEntry[] {
	if (typeof window === 'undefined' || !machineKey) return [];
	const normalized: RecentSortingProfileEntry = {
		...entry,
		last_used_at: entry.last_used_at ?? new Date().toISOString()
	};
	const existing = loadRecentSortingProfiles(machineKey).filter((candidate) => !sameEntry(candidate, normalized));
	const next = [normalized, ...existing].slice(0, MAX_RECENT_SORTING_PROFILES);
	window.localStorage.setItem(storageKey(machineKey), JSON.stringify(next));
	return next;
}

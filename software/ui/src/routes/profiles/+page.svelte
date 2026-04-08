<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ProfileRuleTreeNode from '$lib/components/ProfileRuleTreeNode.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';
	import { Ellipsis, RotateCw } from 'lucide-svelte';

	type SortingProfileRuleSummary = {
		name: string;
		rule_type: 'set' | 'filter' | string;
		set_source?: 'custom' | 'rebrickable' | null;
		set_num?: string | null;
		set_meta?: {
			name?: string | null;
			year?: number | null;
			img_url?: string | null;
			num_parts?: number | null;
		} | null;
		disabled: boolean;
		condition_count: number;
		child_count: number;
	};

	type SortingProfileVersionSummary = {
		id: string;
		version_number: number;
		label: string | null;
		change_note: string | null;
		is_published: boolean;
		compiled_part_count: number;
		coverage_ratio: number | null;
		created_at: string;
		rules_summary?: SortingProfileRuleSummary[];
	};

	type SortingProfileCondition = {
		id: string;
		field: string;
		op: string;
		value: unknown;
	};

	type SortingProfileCustomPart = {
		part_num: string;
		color_id?: number | null;
		quantity?: number | null;
		part_name?: string | null;
		color_name?: string | null;
	};

	type SortingProfileRule = {
		id: string;
		rule_type: string;
		name: string;
		match_mode: string;
		conditions: SortingProfileCondition[];
		children: SortingProfileRule[];
		disabled: boolean;
		set_source?: 'custom' | 'rebrickable' | string | null;
		set_num?: string | null;
		include_spares?: boolean;
		set_meta?: {
			name?: string | null;
			year?: number | null;
			img_url?: string | null;
			num_parts?: number | null;
		} | null;
		custom_parts?: SortingProfileCustomPart[];
	};

	type SortingProfileFallbackMode = {
		rebrickable_categories?: boolean;
		bricklink_categories?: boolean;
		by_color?: boolean;
	};

	type SortingProfileVersionDetail = SortingProfileVersionSummary & {
		name: string;
		description: string | null;
		default_category_id: string;
		rules: SortingProfileRule[];
		fallback_mode: SortingProfileFallbackMode;
		compiled_stats?: {
			matched?: number;
			total_parts?: number;
			unmatched?: number;
			per_category?: Record<string, number>;
		} | null;
		categories?: Record<string, Record<string, unknown>>;
	};

	type SortingProfileSummary = {
		id: string;
		name: string;
		description: string | null;
		is_owner: boolean;
		visibility: 'private' | 'unlisted' | 'public';
		profile_type?: 'rule' | 'set' | string;
		tags: string[];
		latest_version_number?: number | null;
		latest_published_version_number?: number | null;
		fork_count?: number;
		source?: unknown;
		owner?: {
			display_name?: string | null;
			github_login?: string | null;
		} | null;
		latest_version: SortingProfileVersionSummary | null;
		latest_published_version: SortingProfileVersionSummary | null;
	};

	type SortingProfileDetail = SortingProfileSummary & {
		versions: SortingProfileVersionSummary[];
		current_version: SortingProfileVersionDetail | null;
	};

	type SortingProfileSyncState = {
		target_id?: string | null;
		target_name?: string | null;
		target_url?: string | null;
		profile_id?: string | null;
		profile_name?: string | null;
		version_id?: string | null;
		version_number?: number | null;
		version_label?: string | null;
		artifact_hash?: string | null;
		applied_at?: string | null;
		activated_at?: string | null;
		last_error?: string | null;
		progress_last_synced_at?: string | null;
		progress_last_error?: string | null;
	};

	type LocalProfileStatus = {
		path?: string | null;
		name?: string | null;
		description?: string | null;
		artifact_hash?: string | null;
		default_category_id?: string | null;
		category_count?: number | null;
		rule_count?: number | null;
		updated_at?: string | null;
		error?: string | null;
	};

	type MachineProfileAssignment = {
		profile: SortingProfileSummary | null;
		desired_version: SortingProfileVersionSummary | null;
		active_version: SortingProfileVersionSummary | null;
		last_error: string | null;
		last_synced_at: string | null;
		last_activated_at: string | null;
	};

	type SortHiveTargetLibrary = {
		id: string;
		name: string;
		url: string;
		enabled: boolean;
		machine_id: string | null;
		profiles: SortingProfileSummary[];
		assignment: MachineProfileAssignment | null;
		error: string | null;
	};

	type SortingProfileLibraryResponse = {
		targets: SortHiveTargetLibrary[];
		sync_state: SortingProfileSyncState | null;
		local_profile: LocalProfileStatus;
	};

	type PendingProfileApply = {
		key: string;
		target_id: string;
		target_name: string;
		profile_id: string;
		profile_name: string;
		version_id: string;
		version_number: number | null;
		version_label: string | null;
	};

	type SortingProfileCardEntry = {
		target: SortHiveTargetLibrary;
		profile: SortingProfileSummary;
	};

	const manager = getMachinesContext();
	const PROFILE_PAGE_SIZE_OPTIONS = [12, 24, 48] as const;

	let loading = $state(true);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let warning = $state<string | null>(null);
	let library = $state<SortingProfileLibraryResponse | null>(null);
	let detailCache = $state<Record<string, SortingProfileDetail>>({});
	let detailErrors = $state<Record<string, string>>({});
	let selectedVersionIds = $state<Record<string, string>>({});
	let loadingDetailKeys = $state<Record<string, boolean>>({});
	let versionDetailCache = $state<Record<string, SortingProfileDetail>>({});
	let versionDetailErrors = $state<Record<string, string>>({});
	let loadingVersionDetailKeys = $state<Record<string, boolean>>({});
	let applyingKey = $state<string | null>(null);
	let reloadingRuntime = $state(false);
	let lastMachineUrl = '';
	let searchQuery = $state('');
	let currentPage = $state(1);
	let pageSize = $state<number>(12);
	let detailsModalOpen = $state(false);
	let detailsModalTargetId = $state<string | null>(null);
	let detailsModalProfileId = $state<string | null>(null);
	let applyConfirmOpen = $state(false);
	let pendingApply = $state<PendingProfileApply | null>(null);
	let openVersionMenuKey = $state<string | null>(null);
	const detailsModalVersionSelectId = 'profile-details-version-select';

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function detailKey(targetId: string, profileId: string) {
		return `${targetId}:${profileId}`;
	}

	function versionDetailKey(targetId: string, profileId: string, versionId: string) {
		return `${targetId}:${profileId}:${versionId}`;
	}

	function visibleVersions(detail: SortingProfileDetail): SortingProfileVersionSummary[] {
		return detail.is_owner ? detail.versions : detail.versions.filter((version) => version.is_published);
	}

	/**
	 * Find the highest available version number for the currently active profile
	 * across all targets. Returns null if no match or no newer version found.
	 */
	function findLatestAvailableVersion(): { version_number: number; target_name: string } | null {
		if (!library?.sync_state?.profile_id) return null;
		const activeProfileId = library.sync_state.profile_id;
		const currentVersion = library.sync_state.version_number ?? 0;
		let best: { version_number: number; target_name: string } | null = null;

		for (const target of library.targets) {
			for (const profile of target.profiles) {
				if (profile.id !== activeProfileId) continue;
				const latestPublished = profile.latest_published_version ?? profile.latest_version;
				if (!latestPublished) continue;
				if (latestPublished.version_number > currentVersion) {
					if (!best || latestPublished.version_number > best.version_number) {
						best = { version_number: latestPublished.version_number, target_name: target.name };
					}
				}
			}
		}
		return best;
	}

	/**
	 * Check if a specific profile (by ID) has an update available relative to
	 * the currently active sync_state version.
	 */
	function profileHasUpdate(profile: SortingProfileSummary): { latest: number; current: number } | null {
		if (!library?.sync_state?.profile_id) return null;
		if (profile.id !== library.sync_state.profile_id) return null;
		const currentVersion = library.sync_state.version_number ?? 0;
		const latestPublished = profile.latest_published_version ?? profile.latest_version;
		if (!latestPublished) return null;
		if (latestPublished.version_number > currentVersion) {
			return { latest: latestPublished.version_number, current: currentVersion };
		}
		return null;
	}

	function displayVersion(profile: SortingProfileSummary): SortingProfileVersionSummary | null {
		return profile.latest_published_version ?? profile.latest_version;
	}

	function rulesForCard(profile: SortingProfileSummary): SortingProfileRuleSummary[] {
		return (displayVersion(profile)?.rules_summary ?? []).filter((rule) => !rule.disabled);
	}

	function sourceLabel(target: SortHiveTargetLibrary): string {
		return target.name || target.url || 'Unknown source';
	}

	function targetWebUrl(target: SortHiveTargetLibrary): string | null {
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

	function lastUsedAt(target: SortHiveTargetLibrary, profile: SortingProfileSummary): string | null {
		if (library?.sync_state?.profile_id === profile.id) {
			return library.sync_state.activated_at ?? library.sync_state.applied_at ?? null;
		}
		const assignment = target.assignment;
		if (assignment?.profile?.id === profile.id) {
			return assignment.last_activated_at ?? assignment.last_synced_at ?? null;
		}
		return null;
	}

	function profileTitleClass(profile: SortingProfileSummary, isActive: boolean): string {
		if (isActive) return 'text-primary';
		if (profile.visibility === 'public') return 'text-primary dark:text-blue-400';
		return 'text-text';
	}

	function selectedVersionIdForCard(
		targetId: string,
		profile: SortingProfileSummary,
		detail: SortingProfileDetail | undefined
	): string | null {
		const key = detailKey(targetId, profile.id);
		return selectedVersionIds[key] ?? (detail ? visibleVersions(detail)[0]?.id ?? null : null);
	}

	function isActiveSelection(
		targetId: string,
		profile: SortingProfileSummary,
		detail: SortingProfileDetail | undefined
	): boolean {
		const selectedVersionId = selectedVersionIdForCard(targetId, profile, detail);
		return (
			library?.sync_state?.profile_id === profile.id &&
			Boolean(selectedVersionId) &&
			library?.sync_state?.version_id === selectedVersionId
		);
	}

	async function loadLibrary() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/sorting-profiles/library`);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			library = await res.json();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load sorting profile library';
		} finally {
			loading = false;
		}
	}

	async function loadProfileDetail(
		targetId: string,
		profile: SortingProfileSummary
	): Promise<SortingProfileDetail | null> {
		const key = detailKey(targetId, profile.id);
		if (detailCache[key]) return detailCache[key];
		if (loadingDetailKeys[key]) return null;
		loadingDetailKeys = { ...loadingDetailKeys, [key]: true };
		try {
			const res = await fetch(`${baseUrl()}/api/sorting-profiles/targets/${encodeURIComponent(targetId)}/profiles/${encodeURIComponent(profile.id)}`);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const detail = (await res.json()) as SortingProfileDetail;
			detailCache = { ...detailCache, [key]: detail };

			// Pre-select version: for the active profile, pick the next available
			// version (latest); for others, pick the latest version
			const versions = visibleVersions(detail);
			let preselect = versions[0]?.id ?? '';

			if (library?.sync_state?.profile_id === profile.id && library.sync_state.version_id) {
				// For the active profile, prefer the latest version (which may be newer)
				preselect = versions[0]?.id ?? library.sync_state.version_id;
			}

			selectedVersionIds = {
				...selectedVersionIds,
				[key]: preselect
			};
			if (detailErrors[key]) {
				const { [key]: _ignore, ...rest } = detailErrors;
				detailErrors = rest;
			}
			return detail;
		} catch (e: unknown) {
			detailErrors = {
				...detailErrors,
				[key]: e instanceof Error ? e.message : 'Failed to load profile versions'
			};
			return null;
		} finally {
			const { [key]: _ignore, ...rest } = loadingDetailKeys;
			loadingDetailKeys = rest;
		}
	}

	async function loadProfileVersionDetail(
		targetId: string,
		profile: SortingProfileSummary,
		versionId: string
	): Promise<SortingProfileDetail | null> {
		const key = versionDetailKey(targetId, profile.id, versionId);
		if (versionDetailCache[key]) return versionDetailCache[key];
		if (loadingVersionDetailKeys[key]) return null;
		loadingVersionDetailKeys = { ...loadingVersionDetailKeys, [key]: true };
		try {
			const url = new URL(
				`${baseUrl()}/api/sorting-profiles/targets/${encodeURIComponent(targetId)}/profiles/${encodeURIComponent(profile.id)}`
			);
			url.searchParams.set('version_id', versionId);
			const res = await fetch(url.toString());
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const detail = (await res.json()) as SortingProfileDetail;
			versionDetailCache = { ...versionDetailCache, [key]: detail };
			if (versionDetailErrors[key]) {
				const { [key]: _ignore, ...rest } = versionDetailErrors;
				versionDetailErrors = rest;
			}
			return detail;
		} catch (e: unknown) {
			versionDetailErrors = {
				...versionDetailErrors,
				[key]: e instanceof Error ? e.message : 'Failed to load this profile version'
			};
			return null;
		} finally {
			const { [key]: _ignore, ...rest } = loadingVersionDetailKeys;
			loadingVersionDetailKeys = rest;
		}
	}

	async function requestApplyProfile(target: SortHiveTargetLibrary, profile: SortingProfileSummary) {
		await requestApplyProfileVersion(target, profile, null);
	}

	async function requestApplyProfileVersion(
		target: SortHiveTargetLibrary,
		profile: SortingProfileSummary,
		versionId: string | null
	) {
		const key = detailKey(target.id, profile.id);
		const detail = detailCache[key] ?? (await loadProfileDetail(target.id, profile));
		if (!detail) {
			error = detailErrors[key] ?? 'Failed to load profile versions.';
			return;
		}
		const version = versionId
			? visibleVersions(detail).find((entry) => entry.id === versionId)
			: visibleVersions(detail)[0];
		if (!version) {
			error = 'No version available for this profile.';
			return;
		}

		openVersionMenuKey = null;

		pendingApply = {
			key,
			target_id: target.id,
			target_name: target.name,
			profile_id: profile.id,
			profile_name: profile.name,
			version_id: version.id,
			version_number: version.version_number ?? null,
			version_label: version.label ?? null
		};
		applyConfirmOpen = true;
	}

	function toggleVersionMenu(key: string) {
		openVersionMenuKey = openVersionMenuKey === key ? null : key;
	}

	function closeVersionMenu() {
		openVersionMenuKey = null;
	}

	async function confirmApplyProfile() {
		if (!pendingApply) return;
		const applyRequest = pendingApply;
		applyConfirmOpen = false;

		applyingKey = applyRequest.key;
		error = null;
		success = null;
		warning = null;
		try {
			const res = await fetch(`${baseUrl()}/api/sorting-profiles/apply`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_id: applyRequest.target_id,
					profile_id: applyRequest.profile_id,
					profile_name: applyRequest.profile_name,
					version_id: applyRequest.version_id,
					version_number: applyRequest.version_number,
					version_label: applyRequest.version_label,
					reset_bin_categories: true
				})
			});
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const payload = await res.json();
			if (payload.activation_error) {
				success = `Using ${applyRequest.profile_name} locally. Bin assignments were reset.`;
				warning = `SortHive activation could not be confirmed: ${payload.activation_error}`;
			} else {
				success = `Using ${applyRequest.profile_name} on this machine. Bin assignments were reset.`;
			}
			await sortingProfileStore.reload(baseUrl());
			await loadLibrary();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to apply sorting profile';
		} finally {
			pendingApply = null;
			applyingKey = null;
		}
	}

	async function reloadRuntimeProfile() {
		reloadingRuntime = true;
		error = null;
		success = null;
		warning = null;
		try {
			const res = await fetch(`${baseUrl()}/api/sorting-profiles/reload`, { method: 'POST' });
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			await sortingProfileStore.reload(baseUrl());
			await loadLibrary();
			success = 'Reloaded the current sorting profile from disk.';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to reload sorting profile';
		} finally {
			reloadingRuntime = false;
		}
	}

	function formatRelativeTime(value: unknown): string | null {
		if (typeof value !== 'string' || !value) return null;
		const date = new Date(value);
		const now = new Date();
		const diffMs = now.getTime() - date.getTime();
		const diffSec = Math.floor(diffMs / 1000);
		if (diffSec < 60) return 'just now';
		const diffMin = Math.floor(diffSec / 60);
		if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? '' : 's'} ago`;
		const diffHr = Math.floor(diffMin / 60);
		if (diffHr < 24) return `${diffHr} hour${diffHr === 1 ? '' : 's'} ago`;
		const diffDay = Math.floor(diffHr / 24);
		return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`;
	}

	function formatAbsoluteTime(value: unknown): string | null {
		if (typeof value !== 'string' || !value) return null;
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return null;
		return date.toLocaleString();
	}

	function normalizedSearchQuery(): string {
		return searchQuery.trim().toLowerCase();
	}

	function searchableProfileText(profile: SortingProfileSummary): string {
		const ruleBits = rulesForCard(profile).flatMap((rule) => [
			rule.name,
			rule.set_num,
			rule.set_meta?.name,
			rule.set_meta?.year != null ? String(rule.set_meta.year) : null
		]);
		const owner = profile.owner;
		return [
			profile.name,
			profile.description,
			profile.profile_type,
			profile.visibility,
			...(profile.tags ?? []),
			owner?.display_name,
			owner?.github_login,
			...ruleBits
		]
			.filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
			.join(' ')
			.toLowerCase();
	}

	function allProfileEntries(): SortingProfileCardEntry[] {
		if (!library) return [];
		return library.targets.flatMap((target) =>
			target.profiles.map((profile) => ({ target, profile }))
		);
	}

	function filteredProfileEntries(): SortingProfileCardEntry[] {
		const query = normalizedSearchQuery();
		const entries = allProfileEntries();
		if (!query) return entries;
		return entries.filter(({ profile, target }) => {
			const haystack = [searchableProfileText(profile), target.name, target.url]
				.filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
				.join(' ')
				.toLowerCase();
			return haystack.includes(query);
		});
	}

	function filteredProfileCount(): number {
		return filteredProfileEntries().length;
	}

	function totalProfileCount(): number {
		return allProfileEntries().length;
	}

	function totalPages(): number {
		return Math.max(1, Math.ceil(filteredProfileEntries().length / pageSize));
	}

	function currentListPage(): number {
		return Math.min(Math.max(currentPage, 1), totalPages());
	}

	function paginatedProfileEntries(): SortingProfileCardEntry[] {
		const filtered = filteredProfileEntries();
		const page = currentListPage();
		const start = (page - 1) * pageSize;
		return filtered.slice(start, start + pageSize);
	}

	function paginationSummary(): string {
		const filtered = filteredProfileEntries();
		if (filtered.length === 0) return '0 profiles';
		if (filtered.length <= pageSize) {
			return `${filtered.length} profile${filtered.length === 1 ? '' : 's'}`;
		}
		const page = currentListPage();
		const start = (page - 1) * pageSize + 1;
		const end = Math.min(page * pageSize, filtered.length);
		return `${start}-${end} of ${filtered.length}`;
	}

	function setListPage(nextPage: number) {
		currentPage = Math.min(Math.max(nextPage, 1), totalPages());
	}

	function visiblePageNumbers(): number[] {
		const total = totalPages();
		const current = currentListPage();
		const start = Math.max(1, current - 2);
		const end = Math.min(total, start + 4);
		const adjustedStart = Math.max(1, end - 4);
		const pages: number[] = [];
		for (let page = adjustedStart; page <= end; page += 1) {
			pages.push(page);
		}
		return pages;
	}

	function targetErrors(): SortHiveTargetLibrary[] {
		if (!library) return [];
		return library.targets.filter((target) => Boolean(target.error));
	}

	function selectedVersionIdFor(targetId: string, profileId: string): string | null {
		return selectedVersionIds[detailKey(targetId, profileId)] ?? null;
	}

	function activeDetailsModalKey(): string | null {
		if (!detailsModalTargetId || !detailsModalProfileId) return null;
		return detailKey(detailsModalTargetId, detailsModalProfileId);
	}

	function activeDetailsModalVersionKey(): string | null {
		if (!detailsModalTargetId || !detailsModalProfileId) return null;
		const versionId = selectedVersionIdFor(detailsModalTargetId, detailsModalProfileId);
		if (!versionId) return null;
		return versionDetailKey(detailsModalTargetId, detailsModalProfileId, versionId);
	}

	function activeDetailsModalSummary(): SortingProfileDetail | null {
		const key = activeDetailsModalKey();
		return key ? detailCache[key] ?? null : null;
	}

	function activeDetailsModalDetail(): SortingProfileDetail | null {
		const summary = activeDetailsModalSummary();
		const versionKey = activeDetailsModalVersionKey();
		if (versionKey && versionDetailCache[versionKey]) {
			return versionDetailCache[versionKey];
		}
		const selectedVersionId =
			detailsModalTargetId && detailsModalProfileId
				? selectedVersionIdFor(detailsModalTargetId, detailsModalProfileId)
				: null;
		if (
			summary &&
			(!selectedVersionId || summary.current_version?.id === selectedVersionId)
		) {
			return summary;
		}
		return null;
	}

	function activeDetailsModalError(): string | null {
		const versionKey = activeDetailsModalVersionKey();
		if (versionKey && versionDetailErrors[versionKey]) {
			return versionDetailErrors[versionKey];
		}
		const key = activeDetailsModalKey();
		return key ? detailErrors[key] ?? null : null;
	}

	function activeDetailsModalLoading(): boolean {
		const versionKey = activeDetailsModalVersionKey();
		if (versionKey && loadingVersionDetailKeys[versionKey]) return true;
		const key = activeDetailsModalKey();
		return key ? Boolean(loadingDetailKeys[key]) : false;
	}

	function categoryEntries(detail: SortingProfileDetail | null): [string, Record<string, unknown>][] {
		if (!detail?.current_version?.categories) return [];
		return Object.entries(detail.current_version.categories);
	}

	async function openProfileDetails(target: SortHiveTargetLibrary, profile: SortingProfileSummary) {
		const key = detailKey(target.id, profile.id);
		const summary = detailCache[key] ?? (await loadProfileDetail(target.id, profile));
		if (!summary) {
			error = detailErrors[key] ?? 'Failed to load profile details.';
			return;
		}
		const versionId = selectedVersionIds[key] || visibleVersions(summary)[0]?.id || '';
		if (versionId) {
			selectedVersionIds = {
				...selectedVersionIds,
				[key]: versionId
			};
		}
		detailsModalTargetId = target.id;
		detailsModalProfileId = profile.id;
		detailsModalOpen = true;
		if (versionId) {
			await loadProfileVersionDetail(target.id, profile, versionId);
		}
	}

	async function handleVersionSelection(
		target: SortHiveTargetLibrary,
		profile: SortingProfileSummary,
		versionId: string
	) {
		const key = detailKey(target.id, profile.id);
		selectedVersionIds = {
			...selectedVersionIds,
			[key]: versionId
		};
		if (detailsModalOpen && detailsModalTargetId === target.id && detailsModalProfileId === profile.id && versionId) {
			await loadProfileVersionDetail(target.id, profile, versionId);
		}
	}

	/** Auto-load profile detail for the currently visible cards. */
	async function autoLoadVisibleDetails() {
		if (!library) return;
		for (const entry of paginatedProfileEntries()) {
			const target = entry.target;
			const profile = entry.profile;
			const key = detailKey(target.id, profile.id);
			if (!detailCache[key] && !detailErrors[key] && !loadingDetailKeys[key]) {
				try {
					await loadProfileDetail(target.id, profile);
				} catch {
					// Silently ignore — user can retry manually
				}
			}
		}
	}

	$effect(() => {
		const currentUrl = manager.selectedMachine?.url ?? '';
		if (currentUrl === lastMachineUrl) return;
		lastMachineUrl = currentUrl;
		detailCache = {};
		detailErrors = {};
		selectedVersionIds = {};
		loadingDetailKeys = {};
		versionDetailCache = {};
		versionDetailErrors = {};
		loadingVersionDetailKeys = {};
		currentPage = 1;
		detailsModalOpen = false;
		detailsModalTargetId = null;
		detailsModalProfileId = null;
		void loadLibrary();
	});

	// Auto-load versions whenever the visible card set changes.
	$effect(() => {
		if (library && library.targets.length > 0) {
			void autoLoadVisibleDetails();
		}
	});

	onMount(() => {
		void loadLibrary();
		const interval = setInterval(() => void loadLibrary(), 10000);
		return () => clearInterval(interval);
	});
</script>

<svelte:window onclick={closeVersionMenu} />

<svelte:head><title>Sorting Profiles - Sorter</title></svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-4 sm:p-6">

	<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
		<h2 class="text-xl font-bold text-text">Sorting Profiles</h2>
		<div class="flex min-w-[24rem] max-w-[36rem] flex-1 items-center justify-end gap-2">
			<input
				id="profile-search"
				type="search"
				value={searchQuery}
				oninput={(event) => {
					searchQuery = (event.currentTarget as HTMLInputElement).value;
					currentPage = 1;
				}}
				placeholder="Search profiles, sets, tags, owners..."
				class="w-full max-w-md border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-text-muted focus:outline-none"
			/>
			<button
				onclick={reloadRuntimeProfile}
				disabled={reloadingRuntime}
				class="flex items-center justify-center border border-border bg-surface p-2 text-text transition-colors hover:bg-bg disabled:opacity-50"
				title="Reload runtime profile from disk"
			>
				<RotateCw size={16} class={reloadingRuntime ? 'animate-spin' : ''} />
			</button>
		</div>
	</div>

	<StatusBanner message={success ?? ''} variant="success" />
	<StatusBanner message={warning ?? ''} variant="warning" />
	<StatusBanner message={error ?? ''} variant="error" />

	{#if loading && !library}
		<Spinner />
	{:else if !library}
		<p class="text-text-muted">No sorting profile data available.</p>
	{:else}
		<!-- Available Profiles -->
		{#if library.targets.length === 0}
			<p class="text-sm text-text-muted">
				No SortHive targets are configured on this machine right now.
				{#if library.local_profile.name}
					The active local profile above still works.
				{/if}
				Add one in <a href="/settings" class="underline hover:text-text">Settings</a>.
			</p>
		{:else}
			{#if normalizedSearchQuery() && filteredProfileCount() === 0}
				<div class="border border-border bg-surface px-4 py-6 text-center text-sm text-text-muted">
					No profiles match “{searchQuery.trim()}”.
				</div>
			{/if}

			{#if targetErrors().length > 0}
				<div class="mb-4 space-y-2">
					{#each targetErrors() as target}
						<div class="border border-[#D01012] bg-[#D01012]/10 px-3 py-2 text-sm text-[#D01012] dark:text-red-400">
							{target.name}: {target.error}
						</div>
					{/each}
				</div>
			{/if}

			{#if filteredProfileCount() > 0}
				<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
					{#each paginatedProfileEntries() as entry}
						{@const target = entry.target}
						{@const profile = entry.profile}
						{@const key = detailKey(target.id, profile.id)}
						{@const detail = detailCache[key]}
						{@const update = profileHasUpdate(profile)}
						{@const isActive = library.sync_state?.profile_id === profile.id}
						{@const isSelectedActive = isActiveSelection(target.id, profile, detail)}
						{@const rules = rulesForCard(profile)}
						{@const lastUsed = lastUsedAt(target, profile)}
						<div
							class="setup-card-shell group flex h-full flex-col overflow-hidden border transition-colors {isActive
								? 'border-[#00852B] ring-1 ring-[#00852B]/20'
								: 'border-border hover:border-text-muted'}"
						>
							<div class="setup-card-header px-3 py-2 text-sm">
								<div class="flex items-center justify-between gap-3">
									<div class="min-w-0 flex-1">
										<button
											type="button"
											onclick={() => void openProfileDetails(target, profile)}
											class="flex max-w-full items-center gap-2 truncate text-left text-sm font-semibold {profileTitleClass(profile, isActive)} hover:underline"
										>
											{profile.name}
										</button>
										{#if isActive}
											<div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-muted">
												{#if isActive}
													<span class="border border-[#00852B]/30 bg-[#00852B]/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#00852B]">Active</span>
												{/if}
											</div>
										{/if}
										{#if update}
											<div class="mt-1 text-xs text-amber-600">v{update.latest} available (you're on v{update.current})</div>
										{/if}
									</div>
									<div class="flex shrink-0 items-center gap-2 self-center">
										{#if detailErrors[key]}
											<div class="min-w-[10.5rem] border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">Unavailable</div>
										{:else if detail}
											<div class="relative flex items-stretch">
												<button
													onclick={(event) => {
														event.stopPropagation();
														void requestApplyProfile(target, profile);
													}}
													disabled={applyingKey === key}
													class="border border-border bg-white px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:opacity-50"
												>
													{applyingKey === key ? 'Activating...' : 'activate'}
												</button>
												<button
													type="button"
													onclick={(event) => {
														event.stopPropagation();
														toggleVersionMenu(key);
													}}
													disabled={applyingKey === key}
													class="border border-l-0 border-border bg-white px-2 py-2 text-text transition-colors hover:bg-bg disabled:opacity-50"
													title="Choose version"
												>
													<Ellipsis size={16} />
												</button>
												{#if openVersionMenuKey === key}
													<div class="absolute top-full right-0 z-10 mt-1 min-w-[14rem] border border-border bg-surface shadow-lg">
														{#each visibleVersions(detail) as version}
															<button
																type="button"
																onclick={(event) => {
																	event.stopPropagation();
																	void requestApplyProfileVersion(target, profile, version.id);
																}}
																class="flex w-full items-center justify-between gap-3 border-b border-border px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg last:border-b-0"
															>
																<span>v{version.version_number}{version.label ? ` - ${version.label}` : ''}</span>
																{#if !version.is_published}
																	<span class="text-xs text-text-muted">draft</span>
																{/if}
															</button>
														{/each}
													</div>
												{/if}
											</div>
										{:else}
											<div class="min-w-[10.5rem] border border-border bg-bg px-3 py-2 text-sm text-text opacity-60">Loading...</div>
										{/if}
									</div>
								</div>
							</div>

							{#if rules.length > 0}
								<div class="setup-card-body border-t border-border px-4 py-3">
									<div class="grid gap-x-4 gap-y-1.5 md:grid-cols-2">
										{#each rules.slice(0, 8) as rule}
											<div class="flex items-center gap-2 text-xs" title={rule.set_num ?? rule.name}>
												{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
													<img src={rule.set_meta.img_url} alt="" class="h-5 w-5 shrink-0 object-contain" />
												{:else}
													<svg class="h-3.5 w-3.5 shrink-0 text-text-muted" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.092 1.092a4 4 0 00-5.558-5.558z" clip-rule="evenodd" /><path d="M10.748 13.93l2.523 2.523a9.987 9.987 0 01-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 010-1.186A10.007 10.007 0 012.839 6.02L6.07 9.252a4 4 0 004.678 4.678z" /></svg>
												{/if}
												<span class="truncate text-text">{rule.name}</span>
											</div>
										{/each}
										{#if rules.length > 8}
											<button type="button" onclick={() => void openProfileDetails(target, profile)} class="text-[10px] text-text-muted hover:text-text hover:underline md:col-span-2">+{rules.length - 8} more rules</button>
										{/if}
									</div>
								</div>
							{:else}
								<div class="setup-card-body border-t border-border px-4 py-3"><span class="text-xs text-text-muted">No rules defined</span></div>
							{/if}

							<div class="setup-card-body border-t border-border px-4 py-3">
								<div class="grid items-center gap-3 text-xs text-text-muted md:grid-cols-[1fr_auto_1fr]">
									<div>
										{#if lastUsed}
											<span title={formatAbsoluteTime(lastUsed) ?? undefined} class="cursor-help">
												Last used {formatRelativeTime(lastUsed) ?? 'recently'}
											</span>
										{/if}
									</div>
									<div class="text-center">
									{#if targetWebUrl(target)}
										<a
											href={targetWebUrl(target) ?? undefined}
											target="_blank"
											rel="noreferrer"
											class="transition-colors hover:text-text hover:underline"
											>
												{sourceLabel(target)}
											</a>
										{:else}
											{sourceLabel(target)}
										{/if}
									</div>
									<div class="text-right">
										{#if displayVersion(profile)?.created_at}
											<span title={formatAbsoluteTime(displayVersion(profile)?.created_at) ?? undefined} class="cursor-help">
												Updated {formatRelativeTime(displayVersion(profile)?.created_at) ?? 'recently'}
											</span>
										{/if}
									</div>
								</div>
								{#if detailErrors[key]}
									<div class="mt-2 text-xs text-amber-700 dark:text-amber-300">Could not load versions: {detailErrors[key]}</div>
								{/if}
								{#if isSelectedActive}
									<div class="mt-2 text-xs text-primary">Currently active on this machine.</div>
								{:else if isActive && library.sync_state?.version_number}
									<div class="mt-2 text-xs text-text-muted">This profile is active on v{library.sync_state.version_number}.</div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
				<div class="mt-4 grid items-center gap-3 border border-border bg-surface px-4 py-3 text-sm text-text-muted md:grid-cols-[auto_1fr_auto]">
					<label class="flex items-center gap-2 text-sm text-text-muted">
						<span>Per page</span>
						<select
							value={String(pageSize)}
							onchange={(event) => {
								pageSize = Number((event.currentTarget as HTMLSelectElement).value);
								currentPage = 1;
							}}
							class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
						>
							{#each PROFILE_PAGE_SIZE_OPTIONS as option}
								<option value={option}>{option}</option>
							{/each}
						</select>
					</label>
					<div class="text-center">{paginationSummary()}</div>
					<div class="flex items-center justify-end gap-1">
						<button type="button" onclick={() => setListPage(currentListPage() - 1)} disabled={currentListPage() <= 1} class="border border-border px-3 py-1.5 text-text transition-colors hover:bg-bg disabled:opacity-50">Previous</button>
						{#each visiblePageNumbers() as pageNumber}
							<button
								type="button"
								onclick={() => setListPage(pageNumber)}
								class="border px-3 py-1.5 transition-colors {pageNumber === currentListPage() ? 'border-primary bg-primary text-primary-contrast' : 'border-border text-text hover:bg-bg'}"
							>
								{pageNumber}
							</button>
						{/each}
						<button type="button" onclick={() => setListPage(currentListPage() + 1)} disabled={currentListPage() >= totalPages()} class="border border-border px-3 py-1.5 text-text transition-colors hover:bg-bg disabled:opacity-50">Next</button>
					</div>
				</div>
			{/if}
		{/if}
	{/if}
	</div>

	<Modal bind:open={applyConfirmOpen} title="Activate Profile on Machine">
		{#if pendingApply}
			<div class="space-y-4">
				<div class="border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-text">
					<div class="font-medium text-text">Please empty all physical bins first.</div>
					<div class="mt-2 text-text-muted">
						Activating a different sorting profile will reset all learned bin assignments on
						this machine. After that, bins will be assigned again as parts are sorted.
					</div>
				</div>

				<div class="grid gap-2 border border-border bg-surface px-4 py-3 text-sm text-text-muted">
					<div>
						Target: <span class="font-medium text-text">{pendingApply.target_name}</span>
					</div>
					<div>
						Profile: <span class="font-medium text-text">{pendingApply.profile_name}</span>
					</div>
					<div>
						Version:
						<span class="font-medium text-text">
							v{pendingApply.version_number ?? '?'}
							{pendingApply.version_label ? ` - ${pendingApply.version_label}` : ''}
						</span>
					</div>
				</div>

				<div class="flex flex-wrap justify-end gap-2">
					<button
						type="button"
						onclick={() => {
							applyConfirmOpen = false;
							pendingApply = null;
						}}
						class="border border-border px-3 py-2 text-sm text-text transition-colors hover:bg-bg"
					>
						Cancel
					</button>
					<button
						type="button"
						onclick={() => void confirmApplyProfile()}
						class="border border-primary bg-primary px-3 py-2 text-sm font-medium text-primary-contrast transition-colors hover:bg-primary-hover"
					>
						Empty Bins and Activate
					</button>
				</div>
			</div>
		{/if}
	</Modal>

	<Modal bind:open={detailsModalOpen} title="Profile Details" wide={true}>
		{@const modalSummary = activeDetailsModalSummary()}
		{@const modalDetail = activeDetailsModalDetail()}
		{@const modalError = activeDetailsModalError()}
		{@const modalLoading = activeDetailsModalLoading()}
		{#if !modalSummary}
			<div class="py-6 text-sm text-text-muted">No profile details loaded.</div>
		{:else}
			<div class="space-y-5">
				<div class="flex flex-col gap-4 border border-border bg-surface p-4 lg:flex-row lg:items-start lg:justify-between">
					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<h3 class="text-lg font-semibold text-text">{modalSummary.name}</h3>
							{#if modalSummary.profile_type === 'set'}
								<span class="border border-border bg-bg px-2 py-1 text-xs font-medium text-text-muted">
									Set profile
								</span>
							{/if}
							{#if modalSummary.visibility}
								<span class="border border-border bg-bg px-2 py-1 text-xs font-medium text-text-muted">
									{modalSummary.visibility}
								</span>
							{/if}
						</div>
						{#if modalSummary.description}
							<p class="mt-2 text-sm text-text-muted">{modalSummary.description}</p>
						{/if}
						<div class="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-text-muted">
							<span>
								Owner:
								{modalSummary.owner?.display_name ?? modalSummary.owner?.github_login ?? 'Unknown'}
							</span>
							{#if modalSummary.tags.length > 0}
								<span>Tags: {modalSummary.tags.join(', ')}</span>
							{/if}
							{#if modalDetail?.current_version?.default_category_id}
								<span>Default category: {modalDetail.current_version.default_category_id}</span>
							{/if}
						</div>
					</div>
					<div class="w-full max-w-sm space-y-2">
						<label for={detailsModalVersionSelectId} class="block text-xs font-semibold uppercase tracking-wide text-text-muted">
							Version
						</label>
						<select
							id={detailsModalVersionSelectId}
							value={selectedVersionIdFor(detailsModalTargetId ?? '', detailsModalProfileId ?? '') ?? ''}
							onchange={(event) => {
								const target = library?.targets.find((item) => item.id === detailsModalTargetId);
								const profile = target?.profiles.find((item) => item.id === detailsModalProfileId);
								if (!target || !profile) return;
								void handleVersionSelection(
									target,
									profile,
									(event.currentTarget as HTMLSelectElement).value
								);
							}}
							class="w-full border border-border bg-bg px-3 py-2 text-sm text-text focus:border-text-muted focus:outline-none"
						>
							{#each visibleVersions(modalSummary) as version}
								<option value={version.id}>
									v{version.version_number}
									{version.label ? ` - ${version.label}` : ''}
									{version.is_published ? '' : ' (draft)'}
								</option>
							{/each}
						</select>
						{#if modalDetail?.current_version}
							<div class="text-xs text-text-muted">
								{#if modalDetail.current_version.change_note}
									<div>Change note: {modalDetail.current_version.change_note}</div>
								{/if}
								<div>
									Updated {formatRelativeTime(modalDetail.current_version.created_at) ?? 'recently'}
								</div>
							</div>
						{/if}
					</div>
				</div>

				{#if modalError}
					<div class="border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
						{modalError}
					</div>
				{/if}

				{#if modalLoading && !modalDetail}
					<div class="py-8 text-center text-sm text-text-muted">Loading full profile details...</div>
				{:else if modalDetail?.current_version}
					<div class="grid gap-4 lg:grid-cols-[minmax(0,2fr),minmax(18rem,1fr)]">
						<div class="space-y-4">
							<div class="border border-border bg-surface p-4">
								<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
									Rule Tree
								</div>
								{#if modalDetail.current_version.rules.length > 0}
									<div class="space-y-3">
										{#each modalDetail.current_version.rules as rule (rule.id)}
											<ProfileRuleTreeNode rule={rule} />
										{/each}
									</div>
								{:else}
									<div class="text-sm text-text-muted">This version has no rules.</div>
								{/if}
							</div>
						</div>

						<div class="space-y-4">
							<div class="border border-border bg-surface p-4">
								<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
									Compiled Stats
								</div>
								<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
									<div class="border border-border bg-bg px-3 py-2">
										<div class="text-[11px] uppercase tracking-wide text-text-muted">Matched</div>
										<div class="text-lg font-semibold text-text">
											{(modalDetail.current_version.compiled_stats?.matched ?? 0).toLocaleString()}
										</div>
									</div>
									<div class="border border-border bg-bg px-3 py-2">
										<div class="text-[11px] uppercase tracking-wide text-text-muted">Total parts</div>
										<div class="text-lg font-semibold text-text">
											{(modalDetail.current_version.compiled_stats?.total_parts ?? 0).toLocaleString()}
										</div>
									</div>
									<div class="border border-border bg-bg px-3 py-2">
										<div class="text-[11px] uppercase tracking-wide text-text-muted">Unmatched</div>
										<div class="text-lg font-semibold text-text">
											{(modalDetail.current_version.compiled_stats?.unmatched ?? 0).toLocaleString()}
										</div>
									</div>
									<div class="border border-border bg-bg px-3 py-2">
										<div class="text-[11px] uppercase tracking-wide text-text-muted">Categories</div>
										<div class="text-lg font-semibold text-text">
											{categoryEntries(modalDetail).length.toLocaleString()}
										</div>
									</div>
								</div>
							</div>

							<div class="border border-border bg-surface p-4">
								<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
									Fallback
								</div>
								<div class="flex flex-wrap gap-2">
									<span class="border border-border bg-bg px-2 py-1 text-xs text-text-muted">
										Rebrickable: {modalDetail.current_version.fallback_mode?.rebrickable_categories ? 'On' : 'Off'}
									</span>
									<span class="border border-border bg-bg px-2 py-1 text-xs text-text-muted">
										BrickLink: {modalDetail.current_version.fallback_mode?.bricklink_categories ? 'On' : 'Off'}
									</span>
									<span class="border border-border bg-bg px-2 py-1 text-xs text-text-muted">
										By color: {modalDetail.current_version.fallback_mode?.by_color ? 'On' : 'Off'}
									</span>
								</div>
							</div>

							<div class="border border-border bg-surface p-4">
								<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
									Categories
								</div>
								{#if categoryEntries(modalDetail).length > 0}
									<div class="max-h-[24rem] space-y-2 overflow-y-auto">
										{#each categoryEntries(modalDetail) as [categoryId, category]}
											<div class="border border-border bg-bg px-3 py-2">
												<div class="text-sm font-medium text-text">
													{String(category.name ?? categoryId)}
												</div>
												<div class="mt-1 text-xs text-text-muted">
													<span class="font-mono">{categoryId}</span>
													{#if category.set_num}
														<span class="mx-1">&middot;</span>
														<span>{String(category.set_num)}</span>
													{/if}
													{#if category.year != null}
														<span class="mx-1">&middot;</span>
														<span>{String(category.year)}</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								{:else}
									<div class="text-sm text-text-muted">No category metadata available.</div>
								{/if}
							</div>
						</div>
					</div>
				{:else}
					<div class="text-sm text-text-muted">No version details available for this profile.</div>
				{/if}
			</div>
		{/if}
	</Modal>
</div>

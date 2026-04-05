<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';

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
		current_version: SortingProfileVersionSummary | null;
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

	const manager = getMachinesContext();
	const PROFILES_PAGE_SIZE = 9;

	let loading = $state(true);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let warning = $state<string | null>(null);
	let library = $state<SortingProfileLibraryResponse | null>(null);
	let detailCache = $state<Record<string, SortingProfileDetail>>({});
	let detailErrors = $state<Record<string, string>>({});
	let selectedVersionIds = $state<Record<string, string>>({});
	let loadingDetailKeys = $state<Record<string, boolean>>({});
	let applyingKey = $state<string | null>(null);
	let reloadingRuntime = $state(false);
	let lastMachineUrl = '';
	let searchQuery = $state('');
	let currentPages = $state<Record<string, number>>({});

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

	function profileOwnerLabel(profile: SortingProfileSummary): string | null {
		if (profile.is_owner) return null;
		return profile.owner?.display_name ?? profile.owner?.github_login ?? null;
	}

	function versionBadgeLabel(profile: SortingProfileSummary): string | null {
		const version =
			profile.latest_published_version_number ??
			profile.latest_version_number ??
			displayVersion(profile)?.version_number;
		return version != null ? `v${version}` : null;
	}

	function profileDotClass(profile: SortingProfileSummary, isActive: boolean): string {
		if (isActive) return 'bg-[#D01012]';
		if (profile.visibility === 'public') return 'bg-[#0055BF]';
		return 'bg-text-muted';
	}

	function profileTitleClass(profile: SortingProfileSummary, isActive: boolean): string {
		if (isActive) return 'text-[#D01012]';
		if (profile.visibility === 'public') return 'text-[#0055BF] dark:text-blue-400';
		return 'text-text';
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

	async function applyProfile(target: SortHiveTargetLibrary, profile: SortingProfileSummary) {
		const key = detailKey(target.id, profile.id);
		const detail = detailCache[key] ?? (await loadProfileDetail(target.id, profile));
		if (!detail) {
			error = detailErrors[key] ?? 'Failed to load profile versions.';
			return;
		}
		const versionId = selectedVersionIds[key];
		const version = visibleVersions(detail).find((entry) => entry.id === versionId);
		if (!version) {
			error = 'Please choose a version first.';
			return;
		}

		applyingKey = key;
		error = null;
		success = null;
		warning = null;
		try {
			const res = await fetch(`${baseUrl()}/api/sorting-profiles/apply`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_id: target.id,
					profile_id: profile.id,
					profile_name: profile.name,
					version_id: version.id,
					version_number: version.version_number,
					version_label: version.label
				})
			});
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const payload = await res.json();
			if (payload.activation_error) {
				success = `Using ${profile.name} locally.`;
				warning = `SortHive activation could not be confirmed: ${payload.activation_error}`;
			} else {
				success = `Using ${profile.name} on this machine.`;
			}
			await sortingProfileStore.reload(baseUrl());
			await loadLibrary();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to apply sorting profile';
		} finally {
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

	function filteredProfilesForTarget(target: SortHiveTargetLibrary): SortingProfileSummary[] {
		const query = normalizedSearchQuery();
		if (!query) return target.profiles;
		return target.profiles.filter((profile) => searchableProfileText(profile).includes(query));
	}

	function visibleTargets(): SortHiveTargetLibrary[] {
		if (!library) return [];
		const query = normalizedSearchQuery();
		if (!query) return library.targets;
		return library.targets.filter(
			(target) => Boolean(target.error) || filteredProfilesForTarget(target).length > 0
		);
	}

	function filteredProfileCount(): number {
		if (!library) return 0;
		return library.targets.reduce((total, target) => total + filteredProfilesForTarget(target).length, 0);
	}

	function totalProfileCount(): number {
		if (!library) return 0;
		return library.targets.reduce((total, target) => total + target.profiles.length, 0);
	}

	function totalPagesForTarget(target: SortHiveTargetLibrary): number {
		return Math.max(1, Math.ceil(filteredProfilesForTarget(target).length / PROFILES_PAGE_SIZE));
	}

	function currentPageForTarget(target: SortHiveTargetLibrary): number {
		const page = currentPages[target.id] ?? 1;
		return Math.min(Math.max(page, 1), totalPagesForTarget(target));
	}

	function paginatedProfilesForTarget(target: SortHiveTargetLibrary): SortingProfileSummary[] {
		const filtered = filteredProfilesForTarget(target);
		const page = currentPageForTarget(target);
		const start = (page - 1) * PROFILES_PAGE_SIZE;
		return filtered.slice(start, start + PROFILES_PAGE_SIZE);
	}

	function paginationSummaryForTarget(target: SortHiveTargetLibrary): string {
		const filtered = filteredProfilesForTarget(target);
		if (filtered.length === 0) return '0 profiles';
		if (filtered.length <= PROFILES_PAGE_SIZE) {
			return `${filtered.length} profile${filtered.length === 1 ? '' : 's'}`;
		}
		const page = currentPageForTarget(target);
		const start = (page - 1) * PROFILES_PAGE_SIZE + 1;
		const end = Math.min(page * PROFILES_PAGE_SIZE, filtered.length);
		return `${start}-${end} of ${filtered.length}`;
	}

	function setTargetPage(target: SortHiveTargetLibrary, nextPage: number) {
		const clamped = Math.min(Math.max(nextPage, 1), totalPagesForTarget(target));
		currentPages = {
			...currentPages,
			[target.id]: clamped
		};
	}

	/** Auto-load profile detail for the currently visible cards. */
	async function autoLoadVisibleDetails() {
		if (!library) return;
		for (const target of visibleTargets()) {
			for (const profile of paginatedProfilesForTarget(target)) {
				const key = detailKey(target.id, profile.id);
				if (!detailCache[key] && !detailErrors[key] && !loadingDetailKeys[key]) {
					// Fire and forget, but sequentially to avoid hammering the API
					try {
						await loadProfileDetail(target.id, profile);
					} catch {
						// Silently ignore — user can retry manually
					}
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
		currentPages = {};
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

<svelte:head><title>Sorting Profiles - Sorter</title></svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-4 sm:p-6">

	<div class="mb-4 flex flex-wrap items-center justify-between gap-3">
		<h2 class="text-xl font-bold text-text">Sorting Profiles</h2>
		<button
			onclick={reloadRuntimeProfile}
			disabled={reloadingRuntime}
			class="border border-border px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:opacity-50"
		>
			{reloadingRuntime ? 'Reloading...' : 'Reload from Disk'}
		</button>
	</div>

	<StatusBanner message={success ?? ''} variant="success" />
	<StatusBanner message={warning ?? ''} variant="warning" />
	<StatusBanner message={error ?? ''} variant="error" />

	{#if loading && !library}
		<Spinner />
	{:else if !library}
		<p class="text-text-muted">No sorting profile data available.</p>
	{:else}
		<!-- Active Profile Section -->
		{@const updateInfo = findLatestAvailableVersion()}
		<div class="mb-6 border border-border bg-surface p-4">
			<div class="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[#D01012]">
				<span class="inline-block h-2.5 w-2.5 shrink-0 bg-[#D01012]"></span>
				Active Profile
			</div>
			{#if library.local_profile.name || library.sync_state?.profile_name}
				<div class="mt-2 text-lg font-semibold text-text">
					{String(library.local_profile.name ?? library.sync_state?.profile_name ?? 'Unknown')}
				</div>
				<div class="mt-2 space-y-1 text-sm text-text-muted">
					<div>
						{#if library.sync_state?.version_number}
							Version: v{library.sync_state.version_number}
							{#if library.sync_state?.version_label}
								({library.sync_state.version_label})
							{/if}
							{#if library.sync_state?.applied_at || library.sync_state?.activated_at}
								<span class="mx-1">&middot;</span>
								Applied {formatRelativeTime(library.sync_state.activated_at ?? library.sync_state.applied_at) ?? 'unknown'}
							{/if}
						{:else}
							Version: not tracked
						{/if}
					</div>
					{#if library.sync_state?.target_name || library.sync_state?.target_url}
						<div>
							Source: {library.sync_state.target_name ?? 'SortHive'}
							{#if library.sync_state?.target_url}
								({library.sync_state.target_url})
							{/if}
						</div>
					{/if}
					{#if library.local_profile.category_count != null || library.local_profile.rule_count != null}
						<div>
							{#if library.local_profile.category_count != null}
								{library.local_profile.category_count.toLocaleString()} categories
							{/if}
							{#if library.local_profile.category_count != null && library.local_profile.rule_count != null}
								<span class="mx-1">&middot;</span>
							{/if}
							{#if library.local_profile.rule_count != null}
								{library.local_profile.rule_count.toLocaleString()} rules
							{/if}
						</div>
					{/if}
					<div>
						{#if library.sync_state?.last_error}
							<span class="text-[#D01012]">{library.sync_state.last_error}</span>
						{:else if updateInfo}
							<span class="text-amber-600">
								Update available: v{updateInfo.version_number}
								{#if library.sync_state?.version_number}
									(you're on v{library.sync_state.version_number})
								{/if}
							</span>
						{:else if library.sync_state?.version_number}
							<span class="text-[#00852B]">In sync</span>
						{:else}
							<span class="text-text-muted">No sync state</span>
						{/if}
					</div>
					{#if library.sync_state?.progress_last_error}
						<div>
							<span class="text-[#D01012]">
								Set progress sync failed: {library.sync_state.progress_last_error}
							</span>
						</div>
					{:else if library.sync_state?.progress_last_synced_at}
						<div>
							Set progress synced {formatRelativeTime(library.sync_state.progress_last_synced_at) ?? 'just now'}
						</div>
					{/if}
				</div>
			{:else}
				<div class="mt-2 text-sm text-text-muted">
					No active profile. Apply one from the list below.
				</div>
			{/if}
		</div>

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
			<div class="mb-5 border border-border bg-surface p-4">
				<div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
					<div class="min-w-0 flex-1">
						<label for="profile-search" class="mb-1 block text-xs font-semibold uppercase tracking-wide text-text-muted">
							Search
						</label>
						<input
							id="profile-search"
							type="search"
							value={searchQuery}
							oninput={(event) => {
								searchQuery = (event.currentTarget as HTMLInputElement).value;
								currentPages = {};
							}}
							placeholder="Search profiles, sets, tags, owners..."
							class="w-full border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-text-muted focus:outline-none"
						/>
					</div>
					<div class="text-sm text-text-muted">
						{#if normalizedSearchQuery()}
							Showing {filteredProfileCount().toLocaleString()} of {totalProfileCount().toLocaleString()} profiles
						{:else}
							{totalProfileCount().toLocaleString()} profile{totalProfileCount() === 1 ? '' : 's'} available
						{/if}
					</div>
				</div>
			</div>

			{#if normalizedSearchQuery() && filteredProfileCount() === 0}
				<div class="border border-border bg-surface px-4 py-6 text-center text-sm text-text-muted">
					No profiles match “{searchQuery.trim()}”.
				</div>
			{/if}

			{#each visibleTargets() as target}
				{@const filteredProfiles = filteredProfilesForTarget(target)}
				{@const paginatedProfiles = paginatedProfilesForTarget(target)}
				{@const pageCount = totalPagesForTarget(target)}
				{@const page = currentPageForTarget(target)}
				<div class="mb-6">
					<div class="mb-3 flex flex-wrap items-center gap-3">
						<div class="flex min-w-0 flex-1 items-center gap-3">
							<div class="h-px flex-1 bg-border"></div>
							<span class="text-xs font-semibold uppercase tracking-wide text-text-muted">
								Available from {target.name}
							</span>
							<div class="h-px flex-1 bg-border"></div>
						</div>
						<div class="text-xs text-text-muted">{paginationSummaryForTarget(target)}</div>
					</div>

					{#if target.error}
						<div class="mb-3 border border-[#D01012] bg-[#D01012]/10 px-3 py-2 text-sm text-[#D01012] dark:text-red-400">
							{target.error}
						</div>
					{/if}

					{#if target.profiles.length === 0}
						<p class="text-sm text-text-muted">
							No profiles available from this target. Save profiles to your library in SortHive first.
						</p>
					{:else if filteredProfiles.length === 0}
						<p class="text-sm text-text-muted">No profiles from this target match the current search.</p>
					{:else}
						<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
							{#each paginatedProfiles as profile}
								{@const key = detailKey(target.id, profile.id)}
								{@const detail = detailCache[key]}
								{@const update = profileHasUpdate(profile)}
								{@const isActive = library.sync_state?.profile_id === profile.id}
								{@const rules = rulesForCard(profile)}
								<div
									class="group flex h-full flex-col border bg-surface transition-colors {isActive
										? 'border-[#D01012]'
										: 'border-border hover:border-text-muted'}"
								>
									<div class="px-4 pt-4 pb-3">
										<div class="flex items-start justify-between gap-2">
											<div class="min-w-0">
												<h4 class="flex items-center gap-2 truncate text-sm font-semibold {profileTitleClass(profile, isActive)}">
													<span class="inline-block h-2.5 w-2.5 shrink-0 {profileDotClass(profile, isActive)}"></span>
													{profile.name}
												</h4>
												{#if profile.description}
													<p class="mt-0.5 truncate text-xs text-text-muted">{profile.description}</p>
												{/if}
												{#if update}
													<div class="mt-1 text-xs text-amber-600">
														v{update.latest} available (you're on v{update.current})
													</div>
												{:else if displayVersion(profile)}
													<div class="mt-1 text-xs text-text-muted">
														{#if displayVersion(profile)?.label}
															{displayVersion(profile)?.label}
														{:else}
															Updated {formatRelativeTime(displayVersion(profile)?.created_at) ?? 'recently'}
														{/if}
													</div>
												{/if}
											</div>
											<div class="flex shrink-0 items-center gap-1.5">
												{#if profile.source}
													<span class="border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300">
														Fork
													</span>
												{/if}
												{#if profile.profile_type === 'set'}
													<span class="border border-border bg-bg px-1.5 py-0.5 text-[10px] font-medium text-text-muted">
														Set
													</span>
												{/if}
												{#if versionBadgeLabel(profile)}
													<span class="border border-border bg-bg px-1.5 py-0.5 text-[10px] font-medium text-text-muted">
														{versionBadgeLabel(profile)}
													</span>
												{/if}
											</div>
										</div>
									</div>

									{#if rules.length > 0}
										<div class="border-t border-border px-4 py-2.5">
											<div class="space-y-1.5">
												{#each rules.slice(0, 6) as rule}
													<div class="flex items-center gap-2 text-xs">
														{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
															<img src={rule.set_meta.img_url} alt="" class="h-5 w-5 shrink-0 object-contain" />
														{:else}
															<svg class="h-3.5 w-3.5 shrink-0 text-text-muted" viewBox="0 0 20 20" fill="currentColor">
																<path
																	fill-rule="evenodd"
																	d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.092 1.092a4 4 0 00-5.558-5.558z"
																	clip-rule="evenodd"
																/>
																<path d="M10.748 13.93l2.523 2.523a9.987 9.987 0 01-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 010-1.186A10.007 10.007 0 012.839 6.02L6.07 9.252a4 4 0 004.678 4.678z" />
															</svg>
														{/if}
														<span class="truncate text-text">{rule.name}</span>
														{#if rule.rule_type === 'set' && rule.set_num}
															<span class="shrink-0 font-mono text-[10px] text-text-muted">{rule.set_num}</span>
														{:else if rule.condition_count > 0}
															<span class="shrink-0 text-[10px] text-text-muted">{rule.condition_count} cond{rule.condition_count !== 1 ? 's' : ''}</span>
														{/if}
														{#if rule.child_count > 0}
															<span class="shrink-0 text-[10px] text-text-muted">+{rule.child_count} sub</span>
														{/if}
													</div>
												{/each}
												{#if rules.length > 6}
													<div class="text-[10px] text-text-muted">+{rules.length - 6} more rules</div>
												{/if}
											</div>
										</div>
									{:else}
										<div class="border-t border-border px-4 py-2.5">
											<span class="text-xs text-text-muted">No rules defined</span>
										</div>
									{/if}

									<div class="mt-auto border-t border-border bg-bg/40 px-4 py-2">
										<div class="flex items-center justify-between gap-3">
											<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-text-muted">
												<span>{displayVersion(profile)?.compiled_part_count ?? 0} parts</span>
												{#if profile.fork_count && profile.fork_count > 0}
													<span class="text-border">|</span>
													<span>{profile.fork_count} forks</span>
												{/if}
												{#if profileOwnerLabel(profile)}
													<span class="text-border">|</span>
													<span>by {profileOwnerLabel(profile)}</span>
												{/if}
											</div>
											{#if profile.tags.length > 0}
												<div class="flex flex-wrap justify-end gap-1">
													{#each profile.tags.slice(0, 3) as tag}
														<span class="border border-border bg-surface px-1.5 py-0.5 text-[10px] text-text-muted">{tag}</span>
													{/each}
												</div>
											{/if}
										</div>
									</div>

									<div class="border-t border-border px-4 py-3">
										<div class="flex flex-wrap items-center gap-2">
											{#if detail}
												<select
													value={selectedVersionIds[key] ?? ''}
													onchange={(event) => {
														selectedVersionIds = {
															...selectedVersionIds,
															[key]: (event.currentTarget as HTMLSelectElement).value
														};
													}}
													class="min-w-[13rem] border border-border bg-bg px-3 py-2 text-sm text-text focus:border-text-muted focus:outline-none"
												>
													{#each visibleVersions(detail) as version}
														<option value={version.id}>
															v{version.version_number}
															{version.label ? ` - ${version.label}` : ''}
															{version.is_published ? '' : ' (draft)'}
														</option>
													{/each}
												</select>
											{:else if detailErrors[key]}
												<div class="min-w-[13rem] border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
													Unavailable
												</div>
											{:else}
												<select
													disabled
													class="min-w-[13rem] border border-border bg-bg px-3 py-2 text-sm text-text opacity-60 focus:border-text-muted focus:outline-none"
												>
													<option>
														{loadingDetailKeys[key] ? 'Loading versions...' : 'Loading...'}
													</option>
												</select>
											{/if}
											<button
												onclick={() => void applyProfile(target, profile)}
												disabled={!detail || !selectedVersionIds[key] || applyingKey === key}
												class="border border-border px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:opacity-50"
											>
												{applyingKey === key ? 'Activating...' : isActive ? 'Use Again' : 'Use'}
											</button>
										</div>
										{#if detailErrors[key]}
											<div class="mt-2 text-xs text-amber-700 dark:text-amber-300">
												Could not load versions: {detailErrors[key]}
											</div>
										{/if}
										{#if isActive}
											<div class="mt-2 text-xs text-[#D01012]">
												Currently active on this machine.
											</div>
										{/if}
									</div>
								</div>
							{/each}
						</div>
						{#if pageCount > 1}
							<div class="mt-4 flex flex-wrap items-center justify-between gap-3 border border-border bg-surface px-4 py-3 text-sm text-text-muted">
								<div>
									Page {page} of {pageCount}
								</div>
								<div class="flex items-center gap-2">
									<button
										type="button"
										onclick={() => setTargetPage(target, page - 1)}
										disabled={page <= 1}
										class="border border-border px-3 py-1.5 text-text transition-colors hover:bg-bg disabled:opacity-50"
									>
										Previous
									</button>
									<button
										type="button"
										onclick={() => setTargetPage(target, page + 1)}
										disabled={page >= pageCount}
										class="border border-border px-3 py-1.5 text-text transition-colors hover:bg-bg disabled:opacity-50"
									>
										Next
									</button>
								</div>
							</div>
						{/if}
					{/if}
				</div>
			{/each}
		{/if}
	{/if}
	</div>
</div>

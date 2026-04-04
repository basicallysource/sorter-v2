<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';

	type SortingProfileVersionSummary = {
		id: string;
		version_number: number;
		label: string | null;
		change_note: string | null;
		is_published: boolean;
		compiled_part_count: number;
		coverage_ratio: number | null;
		created_at: string;
	};

	type SortingProfileSummary = {
		id: string;
		name: string;
		description: string | null;
		is_owner: boolean;
		visibility: 'private' | 'unlisted' | 'public';
		tags: string[];
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

	let loading = $state(true);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let library = $state<SortingProfileLibraryResponse | null>(null);
	let detailCache = $state<Record<string, SortingProfileDetail>>({});
	let selectedVersionIds = $state<Record<string, string>>({});
	let loadingDetailKey = $state<string | null>(null);
	let applyingKey = $state<string | null>(null);
	let reloadingRuntime = $state(false);
	let lastMachineUrl = '';

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

	async function loadProfileDetail(targetId: string, profile: SortingProfileSummary) {
		const key = detailKey(targetId, profile.id);
		if (detailCache[key]) return detailCache[key];
		loadingDetailKey = key;
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
			return detail;
		} finally {
			loadingDetailKey = null;
		}
	}

	async function applyProfile(target: SortHiveTargetLibrary, profile: SortingProfileSummary) {
		const key = detailKey(target.id, profile.id);
		const detail = detailCache[key] ?? (await loadProfileDetail(target.id, profile));
		const versionId = selectedVersionIds[key];
		const version = visibleVersions(detail).find((entry) => entry.id === versionId);
		if (!version) {
			error = 'Please choose a version first.';
			return;
		}

		applyingKey = key;
		error = null;
		success = null;
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
				success = 'Profile applied locally, but SortHive activation status could not be confirmed.';
			} else {
				success = `Applied ${profile.name} v${version.version_number} on this machine.`;
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

	/** Auto-load profile detail for all profiles once library is available */
	async function autoLoadAllDetails() {
		if (!library) return;
		for (const target of library.targets) {
			for (const profile of target.profiles) {
				const key = detailKey(target.id, profile.id);
				if (!detailCache[key]) {
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
		selectedVersionIds = {};
		void loadLibrary();
	});

	// Auto-load versions whenever library changes
	$effect(() => {
		if (library && library.targets.length > 0) {
			void autoLoadAllDetails();
		}
	});

	onMount(() => {
		void loadLibrary();
		const interval = setInterval(() => void loadLibrary(), 10000);
		return () => clearInterval(interval);
	});
</script>

<svelte:head><title>Sorting Profiles - Sorter</title></svelte:head>

<div class="min-h-screen bg-bg p-4 sm:p-6">
	<AppHeader />

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
	<StatusBanner message={error ?? ''} variant="error" />

	{#if loading && !library}
		<Spinner />
	{:else if !library}
		<p class="text-text-muted">No sorting profile data available.</p>
	{:else}
		<!-- Active Profile Section -->
		{@const updateInfo = findLatestAvailableVersion()}
		<div class="mb-6 border-l-4 border-l-blue-500 border border-border bg-surface p-4">
			<div class="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">Active Profile</div>
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
							<span class="text-red-600">{library.sync_state.last_error}</span>
						{:else if updateInfo}
							<span class="text-amber-600">
								Update available: v{updateInfo.version_number}
								{#if library.sync_state?.version_number}
									(you're on v{library.sync_state.version_number})
								{/if}
							</span>
						{:else if library.sync_state?.version_number}
							<span class="text-emerald-600">In sync</span>
						{:else}
							<span class="text-text-muted">No sync state</span>
						{/if}
					</div>
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
				No SortHive targets configured. Add one in <a href="/settings" class="underline hover:text-text">Settings</a>.
			</p>
		{:else}
			{#each library.targets as target}
				<div class="mb-6">
					<div class="mb-3 flex items-center gap-3">
						<div class="h-px flex-1 bg-border"></div>
						<span class="text-xs font-semibold uppercase tracking-wide text-text-muted">
							Available from {target.name}
						</span>
						<div class="h-px flex-1 bg-border"></div>
					</div>

					{#if target.error}
						<div class="mb-3 border border-red-500 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
							{target.error}
						</div>
					{/if}

					{#if target.profiles.length === 0}
						<p class="text-sm text-text-muted">
							No profiles available from this target. Save profiles to your library in SortHive first.
						</p>
					{:else}
						<div class="space-y-3">
							{#each target.profiles as profile}
								{@const key = detailKey(target.id, profile.id)}
								{@const detail = detailCache[key]}
								{@const update = profileHasUpdate(profile)}
								{@const isActive = library.sync_state?.profile_id === profile.id}
								<div class="border border-border bg-surface p-4 {isActive ? 'border-l-4 border-l-blue-500' : ''}">
									<div class="flex flex-wrap items-start justify-between gap-2">
										<div>
											<h4 class="text-sm font-semibold text-text">{profile.name}</h4>
											{#if update}
												<div class="mt-1 text-sm text-amber-600">
													v{update.latest} available (you're on v{update.current})
												</div>
											{:else if !isActive && profile.latest_published_version}
												<div class="mt-1 text-xs text-text-muted">
													v{profile.latest_published_version.version_number}
													{#if profile.latest_published_version.label}
														&middot; {profile.latest_published_version.label}
													{/if}
												</div>
											{/if}
										</div>
									</div>

									<div class="mt-3 flex flex-wrap items-center gap-2">
										<span class="text-xs text-text-muted">Version:</span>
										{#if detail}
											<select
												value={selectedVersionIds[key] ?? ''}
												onchange={(event) => {
													selectedVersionIds = {
														...selectedVersionIds,
														[key]: (event.currentTarget as HTMLSelectElement).value
													};
												}}
												class="border border-border bg-bg px-3 py-2 text-sm text-text focus:border-text-muted focus:outline-none"
											>
												{#each visibleVersions(detail) as version}
													<option value={version.id}>
														v{version.version_number}
														{version.label ? ` - ${version.label}` : ''}
														{version.is_published ? '' : ' (draft)'}
													</option>
												{/each}
											</select>
										{:else}
											<select
												disabled
												class="border border-border bg-bg px-3 py-2 text-sm text-text opacity-60 focus:border-text-muted focus:outline-none"
											>
												<option>
													{loadingDetailKey === key ? 'Loading versions...' : 'Loading...'}
												</option>
											</select>
										{/if}
										<button
											onclick={() => void applyProfile(target, profile)}
											disabled={!detail || !selectedVersionIds[key] || applyingKey === key}
											class="border border-border px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:opacity-50"
										>
											{applyingKey === key ? 'Applying...' : 'Apply'}
										</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	{/if}
</div>

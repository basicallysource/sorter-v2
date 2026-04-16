<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import {
		loadRecentSortingProfiles,
		rememberRecentSortingProfile,
		type RecentSortingProfileEntry
	} from '$lib/sorting-profiles/recent';
	import { formatRelativeTime } from '$lib/sorting-profiles/format';
	import { ChevronDown } from 'lucide-svelte';

	type SortingProfileSyncState = {
		target_id?: string | null;
		target_name?: string | null;
		profile_id?: string | null;
		profile_name?: string | null;
		version_id?: string | null;
		version_number?: number | null;
		version_label?: string | null;
		applied_at?: string | null;
		activated_at?: string | null;
		last_error?: string | null;
	};

	type LocalProfileStatus = {
		name?: string | null;
		description?: string | null;
		category_count?: number | null;
		rule_count?: number | null;
		updated_at?: string | null;
		error?: string | null;
	};

	type SortingProfileStatusResponse = {
		sync_state?: SortingProfileSyncState | null;
		local_profile?: LocalProfileStatus | null;
	};

	type SortingProfileVersionSummary = {
		id: string;
		version_number?: number | null;
		label?: string | null;
		created_at?: string | null;
		rules_summary?: Array<{ disabled?: boolean | null }> | null;
	};

	type SortingProfileSummary = {
		id: string;
		name: string;
		latest_version?: SortingProfileVersionSummary | null;
		latest_published_version?: SortingProfileVersionSummary | null;
	};

	type HiveTargetLibrary = {
		id: string;
		name: string;
		url?: string | null;
		enabled: boolean;
		error?: string | null;
		profiles: SortingProfileSummary[];
	};

	type SortingProfileLibraryResponse = {
		targets: HiveTargetLibrary[];
	};

	type QuickSwitchProfileEntry = {
		target_id: string;
		target_name: string;
		profile_id: string;
		profile_name: string;
		version_id: string;
		version_number: number | null;
		version_label: string | null;
		rule_count: number | null;
		last_used_at: string | null;
		updated_at: string | null;
		sort_timestamp: number;
	};

	const manager = getMachinesContext();
	const MAX_QUICK_SWITCH_PROFILES = 8;

	let dropdown_open = $state(false);
	let loading_status = $state(false);
	let loading_quick_profiles = $state(false);
	let status_error = $state<string | null>(null);
	let quick_profiles_error = $state<string | null>(null);
	let action_error = $state<string | null>(null);
	let action_message = $state<string | null>(null);
	let applying_key = $state<string | null>(null);
	let status = $state<SortingProfileStatusResponse | null>(null);
	let profile_library = $state<SortingProfileLibraryResponse | null>(null);
	let recent_profiles = $state<RecentSortingProfileEntry[]>([]);
	let quick_profiles = $state<QuickSwitchProfileEntry[]>([]);
	let last_machine_key = $state('');

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
	}

	function currentMachineKey(): string | null {
		return manager.selectedMachine?.identity?.machine_id ?? manager.selectedMachineId ?? null;
	}

	function parseTimestamp(value: string | null | undefined): number {
		if (!value) return 0;
		const timestamp = new Date(value).getTime();
		return Number.isFinite(timestamp) ? timestamp : 0;
	}

	function recentEntryKey(entry: Pick<RecentSortingProfileEntry, 'target_id' | 'profile_id' | 'version_id'>): string {
		return `${entry.target_id}::${entry.profile_id}::${entry.version_id}`;
	}

	function recentProfileKey(entry: Pick<RecentSortingProfileEntry, 'target_id' | 'profile_id'>): string {
		return `${entry.target_id}::${entry.profile_id}`;
	}

	function syncStateToRecentEntry(
		syncState: SortingProfileSyncState | null | undefined
	): Omit<RecentSortingProfileEntry, 'last_used_at'> | null {
		if (
			!syncState?.target_id ||
			!syncState.profile_id ||
			!syncState.version_id ||
			!syncState.profile_name
		) {
			return null;
		}
		return {
			target_id: syncState.target_id,
			target_name: syncState.target_name ?? 'Hive',
			profile_id: syncState.profile_id,
			profile_name: syncState.profile_name,
			version_id: syncState.version_id,
			version_number: syncState.version_number ?? null,
			version_label: syncState.version_label ?? null
		};
	}

	function refreshRecentProfiles() {
		recent_profiles = loadRecentSortingProfiles(currentMachineKey());
	}

	function rememberCurrentProfile() {
		const entry = syncStateToRecentEntry(status?.sync_state);
		if (!entry) {
			refreshRecentProfiles();
			rebuildQuickProfiles();
			return;
		}
		recent_profiles = rememberRecentSortingProfile(currentMachineKey(), {
			...entry,
			last_used_at: status?.sync_state?.applied_at ?? null
		});
		rebuildQuickProfiles();
	}

	function latestRemoteVersion(profile: SortingProfileSummary): SortingProfileVersionSummary | null {
		return profile.latest_version ?? profile.latest_published_version ?? null;
	}

	function rebuildQuickProfiles() {
		const byProfile = new Map<string, QuickSwitchProfileEntry>();

		for (const recent of recent_profiles) {
			const key = recentProfileKey(recent);
			byProfile.set(key, {
				...recent,
				rule_count: null,
				last_used_at: recent.last_used_at,
				updated_at: null,
				sort_timestamp: parseTimestamp(recent.last_used_at)
			});
		}

		for (const target of profile_library?.targets ?? []) {
			if (!target.enabled || target.error) continue;
			for (const profile of target.profiles ?? []) {
				const version = latestRemoteVersion(profile);
				if (!version?.id) continue;
				const key = recentProfileKey({ target_id: target.id, profile_id: profile.id });
				const existing = byProfile.get(key);
				const updatedAt = version.created_at ?? null;
				const updatedTimestamp = parseTimestamp(updatedAt);

				if (!existing) {
					byProfile.set(key, {
						target_id: target.id,
						target_name: target.name || target.url || 'Hive',
						profile_id: profile.id,
						profile_name: profile.name,
						version_id: version.id,
						version_number: version.version_number ?? null,
						version_label: version.label ?? null,
						rule_count: Array.isArray(version.rules_summary) ? version.rules_summary.length : null,
						last_used_at: null,
						updated_at: updatedAt,
						sort_timestamp: updatedTimestamp
					});
					continue;
				}

				const lastUsedTimestamp = parseTimestamp(existing.last_used_at);
				if (updatedTimestamp > lastUsedTimestamp) {
					byProfile.set(key, {
						...existing,
						target_name: target.name || target.url || existing.target_name,
						profile_name: profile.name,
						version_id: version.id,
						version_number: version.version_number ?? null,
						version_label: version.label ?? null,
						rule_count: Array.isArray(version.rules_summary) ? version.rules_summary.length : existing.rule_count,
						updated_at: updatedAt,
						sort_timestamp: Math.max(updatedTimestamp, lastUsedTimestamp)
					});
				} else {
					byProfile.set(key, {
						...existing,
						target_name: target.name || target.url || existing.target_name,
						profile_name: existing.profile_name || profile.name,
						rule_count: Array.isArray(version.rules_summary) ? version.rules_summary.length : existing.rule_count,
						updated_at: updatedAt,
						sort_timestamp: Math.max(existing.sort_timestamp, updatedTimestamp)
					});
				}
			}
		}

		const currentKey = current_entry ? recentEntryKey(current_entry) : null;
		quick_profiles = [...byProfile.values()]
			.filter((entry) => recentEntryKey(entry) !== currentKey)
			.sort((a, b) => b.sort_timestamp - a.sort_timestamp || a.profile_name.localeCompare(b.profile_name))
			.slice(0, MAX_QUICK_SWITCH_PROFILES);
	}

	async function loadQuickProfileLibrary() {
		if (!manager.selectedMachineId) {
			profile_library = null;
			quick_profiles_error = null;
			rebuildQuickProfiles();
			return;
		}

		loading_quick_profiles = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/sorting-profiles/library`);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			profile_library = (await res.json()) as SortingProfileLibraryResponse;
			quick_profiles_error = null;
		} catch (e: unknown) {
			profile_library = null;
			quick_profiles_error = e instanceof Error ? e.message : 'Failed to load profile library';
		} finally {
			loading_quick_profiles = false;
			rebuildQuickProfiles();
		}
	}

	async function loadStatus() {
		if (!manager.selectedMachineId) {
			status = null;
			status_error = null;
			recent_profiles = [];
			loading_status = false;
			return;
		}

		loading_status = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/sorting-profiles/status`);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			status = (await res.json()) as SortingProfileStatusResponse;
			status_error = null;
			rememberCurrentProfile();
		} catch (e: unknown) {
			status_error = e instanceof Error ? e.message : 'Failed to load sorting profile status';
			refreshRecentProfiles();
			rebuildQuickProfiles();
		} finally {
			loading_status = false;
		}
	}

	async function toggleDropdown() {
		if (!manager.selectedMachineId) return;
		dropdown_open = !dropdown_open;
		if (dropdown_open) {
			action_error = null;
			action_message = null;
			await Promise.all([loadStatus(), loadQuickProfileLibrary()]);
		}
	}

	function handleClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (!target.closest('.sorting-profile-dropdown')) {
			dropdown_open = false;
		}
	}

	async function applyRecentProfile(entry: QuickSwitchProfileEntry) {
		applying_key = recentEntryKey(entry);
		action_error = null;
		action_message = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/sorting-profiles/apply`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_id: entry.target_id,
					profile_id: entry.profile_id,
					profile_name: entry.profile_name,
					version_id: entry.version_id,
					version_number: entry.version_number,
					version_label: entry.version_label,
					reset_bin_categories: true
				})
			});
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const payload = await res.json().catch(() => null);
			recent_profiles = rememberRecentSortingProfile(currentMachineKey(), { ...entry, last_used_at: null });
			await sortingProfileStore.reload(currentBackendBaseUrl()).catch(() => null);
			await Promise.all([loadStatus(), loadQuickProfileLibrary()]);
			action_message = payload?.activation_error
				? `Applied ${entry.profile_name} locally. Hive activation could not be confirmed.`
				: `Switched to ${entry.profile_name}.`;
		} catch (e: unknown) {
			action_error = e instanceof Error ? e.message : 'Failed to switch sorting profile';
		} finally {
			applying_key = null;
		}
	}

	const current_entry = $derived(syncStateToRecentEntry(status?.sync_state));
	const current_profile_name = $derived(status?.sync_state?.profile_name ?? status?.local_profile?.name ?? 'No profile');
	const current_profile_version = $derived(status?.sync_state?.version_number ?? null);
	const current_profile_version_label = $derived(status?.sync_state?.version_label ?? null);
	const current_profile_target = $derived(status?.sync_state?.target_name ?? 'Local');
	const current_profile_updated = $derived(
		formatRelativeTime(status?.sync_state?.applied_at ?? status?.local_profile?.updated_at)
	);
	function usedSummary(entry: QuickSwitchProfileEntry): string {
		const used = formatRelativeTime(entry.last_used_at);
		return used ? `Used ${used}` : '';
	}

	function updatedSummary(entry: QuickSwitchProfileEntry): string {
		const updated = formatRelativeTime(entry.updated_at);
		return updated ? `Updated ${updated}` : '';
	}

	$effect(() => {
		const machineKey = currentMachineKey() ?? '';
		if (machineKey === last_machine_key) return;
		last_machine_key = machineKey;
		dropdown_open = false;
		action_error = null;
		action_message = null;
		quick_profiles_error = null;
		profile_library = null;
		refreshRecentProfiles();
		rebuildQuickProfiles();
		void loadStatus();
	});

	onMount(() => {
		const interval = setInterval(() => {
			void loadStatus();
		}, 10000);
		return () => clearInterval(interval);
	});
</script>

<svelte:window onclick={handleClickOutside} />

<div class="sorting-profile-dropdown relative">
	<button
		type="button"
		onclick={() => void toggleDropdown()}
		disabled={!manager.selectedMachineId}
		class="flex max-w-[240px] items-center gap-2 border border-border bg-surface px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg disabled:cursor-default disabled:opacity-60"
	>
		<span class="truncate font-medium">{current_profile_name}</span>
		{#if current_profile_version}
			<span class="shrink-0 text-xs text-text-muted">v{current_profile_version}</span>
		{/if}
		<ChevronDown size={14} class="shrink-0 opacity-60" />
	</button>

	{#if dropdown_open}
		<div class="absolute top-full right-0 z-50 mt-1 w-80 overflow-hidden border border-border bg-surface shadow-[0_12px_28px_rgba(15,23,42,0.14)]">
			<div class="px-3 py-3">
				<div class="flex items-center justify-between gap-3">
					<div class="flex min-w-0 items-center gap-2">
						<span class="min-w-0 truncate text-sm font-medium text-text">{current_profile_name}</span>
					</div>
					<div class="flex shrink-0 items-center gap-2">
						{#if current_profile_version}
							<span class="shrink-0 text-xs text-text-muted">
								v{current_profile_version}{current_profile_version_label ? ` - ${current_profile_version_label}` : ''}
							</span>
						{/if}
						<span class="border border-[#00852B]/30 bg-[#00852B]/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#00852B]">Active</span>
					</div>
				</div>
				<div class="mt-1 flex items-center justify-between gap-3 text-xs text-text-muted">
					<span class="min-w-0 truncate">{current_profile_target}</span>
					{#if status?.local_profile?.rule_count !== undefined && status.local_profile.rule_count !== null}
						<span class="shrink-0">{status.local_profile.rule_count} rules</span>
					{/if}
				</div>
				{#if current_profile_updated}
					<div class="mt-1 text-[11px] text-text-muted">Updated {current_profile_updated}</div>
				{/if}
			</div>

			<div class="mx-3 border-t border-[#C9C7C0]"></div>

			<div class="px-3 pb-2 pt-4">
				<div>
					<div class="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">Recent profiles</div>
				</div>
			</div>

			<div>
				{#if action_message}
					<div class="mx-3 mb-2 border border-[#00852B]/20 bg-[#00852B]/8 px-2.5 py-2 text-xs text-[#00852B]">
						{action_message}
					</div>
				{/if}
				{#if action_error}
					<div class="mx-3 mb-2 border border-[#D01012]/20 bg-[#D01012]/8 px-2.5 py-2 text-xs text-[#D01012]">
						{action_error}
					</div>
				{/if}
				{#if status_error}
					<div class="mx-3 mb-2 border border-[#D01012]/20 bg-[#D01012]/8 px-2.5 py-2 text-xs text-[#D01012]">
						{status_error}
					</div>
				{/if}
				{#if quick_profiles_error}
					<div class="mx-3 mb-2 border border-[#D01012]/20 bg-[#D01012]/8 px-2.5 py-2 text-xs text-[#D01012]">
						{quick_profiles_error}
					</div>
				{/if}

				{#if loading_quick_profiles && quick_profiles.length === 0}
					<div class="px-3 pb-3 text-xs text-text-muted">Loading recent profiles...</div>
				{:else if quick_profiles.length === 0}
					<div class="px-3 pb-3 text-xs text-text-muted">Recently used and newly updated profiles will appear here.</div>
				{:else}
					<div class="divide-y divide-border px-3">
						{#each quick_profiles as entry}
							{@const used = usedSummary(entry)}
							{@const updated = updatedSummary(entry)}
							<button
								type="button"
								onclick={() => void applyRecentProfile(entry)}
								disabled={applying_key === recentEntryKey(entry)}
								class="block w-full px-2 py-2.5 text-left transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-60"
							>
								<div class="flex items-center justify-between gap-3">
									<span class="min-w-0 truncate text-sm font-medium text-text">{entry.profile_name}</span>
									<span class="shrink-0 text-xs text-text-muted">
										{#if applying_key === recentEntryKey(entry)}
											Switching...
										{:else if entry.version_number}
											v{entry.version_number}
										{/if}
									</span>
								</div>
								<div class="mt-1 flex items-center justify-between gap-3 text-xs text-text-muted">
									<span class="min-w-0 truncate">{entry.target_name}</span>
									<span class="shrink-0">{entry.rule_count ?? '?'} rules</span>
								</div>
								<div class="mt-1 flex items-center justify-between gap-3 text-[11px] text-text-muted">
									<span class="min-w-0 truncate">{used}</span>
									<span class="min-w-0 truncate text-right">{updated}</span>
								</div>
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<script lang="ts">
	import { untrack } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import {
		loadRecentSortingProfiles,
		rememberRecentSortingProfile,
		type RecentSortingProfileEntry
	} from '$lib/sorting-profiles/recent';
	import { formatRelativeTime } from '$lib/sorting-profiles/format';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';

	type SortingProfileSyncState = {
		source?: 'hive' | 'local' | null;
		local_filename?: string | null;
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
		// Hive's own profiles, which every machine gets.
		is_default?: boolean;
		default_rank?: number | null;
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

	type LocalProfileEntry = {
		filename: string;
		name?: string | null;
		rule_count?: number | null;
		is_active: boolean;
		error?: string | null;
	};

	type SortingProfileLibraryResponse = {
		targets: HiveTargetLibrary[];
		local_profiles?: LocalProfileEntry[];
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
		is_default: boolean;
		default_rank: number | null;
		last_used_at: string | null;
		updated_at: string | null;
		sort_timestamp: number;
	};

	const manager = getMachinesContext();
	const MAX_QUICK_SWITCH_PROFILES = 8;

	let dropdown_open = $state(false);
	let loading_quick_profiles = $state(false);
	let quick_profiles_error = $state<string | null>(null);
	let action_error = $state<string | null>(null);
	let action_message = $state<string | null>(null);
	let applying_key = $state<string | null>(null);
	const status = $derived<SortingProfileStatusResponse | null>(
		(manager.selectedMachine?.sortingProfileStatus as SortingProfileStatusResponse | null | undefined) ?? null
	);
	let profile_library = $state<SortingProfileLibraryResponse | null>(null);
	let recent_profiles = $state<RecentSortingProfileEntry[]>([]);
	let quick_profiles = $state<QuickSwitchProfileEntry[]>([]);
	let last_machine_key = $state('');

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase();
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

		// Set of currently-known (target_id, profile_id) pairs from the live
		// library — used to skip stale recent entries whose target_id no
		// longer exists (e.g. after a hive re-registration).
		const liveTargetIds = new Set<string>(
			(profile_library?.targets ?? []).filter((t) => t.enabled && !t.error).map((t) => t.id)
		);

		for (const recent of recent_profiles) {
			// Drop recent entries pointing at vanished targets — clicking
			// them would just 404 ("Hive target not found.") on apply.
			if (liveTargetIds.size > 0 && !liveTargetIds.has(recent.target_id)) {
				continue;
			}
			const key = recentProfileKey(recent);
			byProfile.set(key, {
				...recent,
				rule_count: null,
				is_default: false,
				default_rank: null,
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
						is_default: Boolean(profile.is_default),
						default_rank: profile.default_rank ?? null,
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
						is_default: Boolean(profile.is_default),
						default_rank: profile.default_rank ?? null,
						updated_at: updatedAt,
						sort_timestamp: Math.max(updatedTimestamp, lastUsedTimestamp)
					});
				} else {
					byProfile.set(key, {
						...existing,
						target_name: target.name || target.url || existing.target_name,
						profile_name: existing.profile_name || profile.name,
						rule_count: Array.isArray(version.rules_summary) ? version.rules_summary.length : existing.rule_count,
						is_default: Boolean(profile.is_default),
						default_rank: profile.default_rank ?? null,
						updated_at: updatedAt,
						sort_timestamp: Math.max(existing.sort_timestamp, updatedTimestamp)
					});
				}
			}
		}

		const currentKey = current_entry ? recentEntryKey(current_entry) : null;
		// The person's own profiles, newest first, then Hive's defaults in their order.
		quick_profiles = [...byProfile.values()]
			.filter((entry) => recentEntryKey(entry) !== currentKey)
			.sort(
				(a, b) =>
					Number(a.is_default) - Number(b.is_default) ||
					(a.is_default
						? (a.default_rank ?? Number.MAX_SAFE_INTEGER) - (b.default_rank ?? Number.MAX_SAFE_INTEGER)
						: b.sort_timestamp - a.sort_timestamp) ||
					a.profile_name.localeCompare(b.profile_name)
			)
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

	// Opening the panel (its button, through the popover) refreshes the lists.
	$effect(() => {
		if (!dropdown_open) return;
		untrack(() => {
			action_error = null;
			action_message = null;
			void loadQuickProfileLibrary();
		});
	});

	const local_profiles = $derived<LocalProfileEntry[]>(profile_library?.local_profiles ?? []);

	let pending_local_profile = $state<LocalProfileEntry | null>(null);
	let local_modal_open = $state(false);

	function requestApplyLocalProfile(profile: LocalProfileEntry) {
		pending_local_profile = profile;
		local_modal_open = true;
		action_error = null;
		action_message = null;
	}

	function cancelApplyLocalProfile() {
		local_modal_open = false;
	}

	async function confirmApplyLocalProfile(mode: 'empty' | 'rules') {
		const profile = pending_local_profile;
		if (profile === null) return;
		local_modal_open = false;
		applying_key = `local::${profile.filename}`;
		action_error = null;
		action_message = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/sorting-profiles/local/apply`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ filename: profile.filename, preassign_mode: mode })
			});
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const payload = await res.json().catch(() => null);
			await sortingProfileStore.reload(currentBackendBaseUrl()).catch(() => null);
			await loadQuickProfileLibrary();
			const label = profile.name || profile.filename;
			const preassigned = payload?.preassigned_count as number | undefined;
			action_message =
				mode === 'rules' && preassigned
					? `Switched to ${label}, pre-assigned ${preassigned} bin${preassigned === 1 ? '' : 's'}.`
					: `Switched to ${label}.`;
		} catch (e: unknown) {
			action_error = e instanceof Error ? e.message : 'Failed to switch sorting profile';
		} finally {
			applying_key = null;
		}
	}

	let pending_switch_entry = $state<QuickSwitchProfileEntry | null>(null);

	function requestApplyRecentProfile(entry: QuickSwitchProfileEntry) {
		pending_switch_entry = entry;
		action_error = null;
		action_message = null;
	}

	function cancelApplyRecentProfile() {
		pending_switch_entry = null;
	}

	async function confirmApplyRecentProfile(mode: 'empty' | 'rules') {
		const entry = pending_switch_entry;
		if (entry === null) return;
		pending_switch_entry = null;
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
					preassign_mode: mode
				})
			});
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const payload = await res.json().catch(() => null);
			recent_profiles = rememberRecentSortingProfile(currentMachineKey(), { ...entry, last_used_at: null });
			await sortingProfileStore.reload(currentBackendBaseUrl()).catch(() => null);
			await loadQuickProfileLibrary();
			const preassigned = payload?.preassigned_count as number | undefined;
			if (mode === 'rules' && preassigned) {
				action_message = `Switched to ${entry.profile_name}, pre-assigned ${preassigned} bin${preassigned === 1 ? '' : 's'}.`;
			} else {
				action_message = payload?.activation_error
					? `Applied ${entry.profile_name} locally. Hive activation could not be confirmed.`
					: `Switched to ${entry.profile_name}.`;
			}
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
	const current_profile_target = $derived.by(() => {
		const ss = status?.sync_state;
		if (ss?.source === 'local') return `local:${ss.local_filename ?? ss.profile_name ?? 'profile'}`;
		if (ss?.target_name) return `hive:${ss.target_name}`;
		return ss?.target_name ?? 'Local';
	});
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
	});

	// Re-remember the currently-applied profile whenever a new WS snapshot arrives.
	// `untrack` so writes to recent_profiles/quick_profiles inside the helper don't
	// loop the effect back through their own deps.
	$effect(() => {
		if (status) {
			untrack(() => rememberCurrentProfile());
		}
	});
</script>

{#snippet meta(parts: (string | null | undefined | false)[])}
	<span class="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm text-ink-muted">
		{#each parts.filter(Boolean) as part, i (i)}
			{#if i > 0}<span aria-hidden="true">·</span>{/if}
			<span class="min-w-0 truncate">{part}</span>
		{/each}
	</span>
{/snippet}

<Popover label="Sorting profile" placement="bottom-end" width="22rem" padded={false} bind:open={dropdown_open}>
	{#snippet trigger(props)}
		<button
			{...props}
			type="button"
			disabled={!manager.selectedMachineId}
			class="flex h-(--size-control-sm) max-w-60 items-center gap-2 rounded-control border border-line-strong bg-field pr-2 pl-2.5 text-sm text-ink transition-colors hover:border-ink-faint disabled:pointer-events-none disabled:opacity-45"
		>
			<span class="truncate font-medium">{current_profile_name}</span>
			{#if current_profile_version}
				<span class="num shrink-0 text-ink-muted">v{current_profile_version}</span>
			{/if}
			<ChevronDown size={16} class="shrink-0 text-ink-muted" />
		</button>
	{/snippet}

	<div class="px-4 py-3">
		<div class="flex items-center justify-between gap-2">
			<span class="min-w-0 truncate font-medium text-ink">{current_profile_name}</span>
			<div class="flex shrink-0 items-center gap-1.5">
				{#if current_profile_version}
					<span class="num text-ink-muted">
						v{current_profile_version}{current_profile_version_label
							? ` · ${current_profile_version_label}`
							: ''}
					</span>
				{/if}
				<Badge tone="success">Active</Badge>
			</div>
		</div>
		{@render meta([
			status?.local_profile?.rule_count != null && `${status.local_profile.rule_count} rules`,
			current_profile_target,
			current_profile_updated && `Updated ${current_profile_updated}`
		])}
	</div>

	{#if action_message || action_error || quick_profiles_error}
		<div class="flex flex-col gap-2 px-4 pb-3">
			{#if action_message}<Alert tone="success">{action_message}</Alert>{/if}
			{#if action_error}<Alert tone="danger">{action_error}</Alert>{/if}
			{#if quick_profiles_error}<Alert tone="danger">{quick_profiles_error}</Alert>{/if}
		</div>
	{/if}

	<div class="max-h-[60dvh] overflow-y-auto">
		<div class="label border-y border-line px-4 py-1.5">Recent</div>
		{#if loading_quick_profiles && quick_profiles.length === 0}
			<div class="flex justify-center px-4 py-3"><Spinner /></div>
		{:else if quick_profiles.length === 0}
			<p class="px-4 py-3 text-ink-muted">No recent profiles yet.</p>
		{:else}
			<div class="divide-y divide-line">
				{#each quick_profiles as entry}
					<button
						type="button"
						onclick={() => requestApplyRecentProfile(entry)}
						disabled={applying_key === recentEntryKey(entry)}
						class="block w-full px-4 py-2.5 text-left transition-colors hover:bg-hover disabled:pointer-events-none disabled:opacity-45"
					>
						<span class="flex items-center justify-between gap-2">
							<span class="min-w-0 truncate font-medium text-ink">{entry.profile_name}</span>
							<span class="num shrink-0 text-ink-muted">
								{#if applying_key === recentEntryKey(entry)}
									Switching
								{:else if entry.version_number}
									v{entry.version_number}
								{/if}
							</span>
						</span>
						{@render meta([
							entry.is_default ? 'Hive default' : `Hive: ${entry.target_name}`,
							entry.rule_count != null && `${entry.rule_count} rules`,
							usedSummary(entry),
							updatedSummary(entry)
						])}
					</button>
				{/each}
			</div>
		{/if}

		<div class="label border-y border-line px-4 py-1.5">On this machine</div>
		{#if loading_quick_profiles && local_profiles.length === 0}
			<div class="flex justify-center px-4 py-3"><Spinner /></div>
		{:else if local_profiles.length === 0}
			<p class="px-4 py-3 text-ink-muted">No local profiles.</p>
		{:else}
			<div class="divide-y divide-line">
				{#each local_profiles as profile}
					<button
						type="button"
						onclick={() => requestApplyLocalProfile(profile)}
						disabled={applying_key === `local::${profile.filename}` || Boolean(profile.error)}
						class="block w-full px-4 py-2.5 text-left transition-colors hover:bg-hover disabled:pointer-events-none disabled:opacity-45"
					>
						<span class="flex items-center justify-between gap-2">
							<span class="min-w-0 truncate font-medium text-ink">{profile.name || profile.filename}</span>
							<span class="shrink-0 text-ink-muted">
								{#if applying_key === `local::${profile.filename}`}
									Switching
								{:else if profile.is_active}
									Active
								{/if}
							</span>
						</span>
						{@render meta([
							profile.filename,
							profile.rule_count != null && `${profile.rule_count} rules`
						])}
					</button>
				{/each}
			</div>
		{/if}
	</div>
</Popover>

{#snippet switchChoices(onpick: (mode: 'empty' | 'rules') => void, cancel: () => void)}
	<Button variant="ghost" onclick={cancel}>Cancel</Button>
	<Button onclick={() => onpick('empty')}>Reset bins</Button>
	<Button variant="primary" onclick={() => onpick('rules')}>Pre-assign from rules</Button>
{/snippet}

<Modal bind:open={local_modal_open} title="Switch the sorting profile" size="sm">
	{#if pending_local_profile !== null}
		<p>Switch to <span class="font-medium">{pending_local_profile.name || pending_local_profile.filename}</span>?</p>
		<p class="mt-2 text-ink-muted">Choose how the bins start with the new profile.</p>
	{/if}
	{#snippet footer()}
		{@render switchChoices((mode) => void confirmApplyLocalProfile(mode), cancelApplyLocalProfile)}
	{/snippet}
</Modal>

<Modal open={pending_switch_entry !== null} title="Switch the sorting profile" size="sm" onclose={cancelApplyRecentProfile}>
	{#if pending_switch_entry !== null}
		<p>Switch to <span class="font-medium">{pending_switch_entry.profile_name}</span>?</p>
		<p class="mt-2 text-ink-muted">Choose how the bins start with the new profile.</p>
		<dl class="mt-3 divide-y divide-line rounded-control bg-well">
			<div class="px-3 py-2">
				<dt class="font-medium text-ink">Reset bins</dt>
				<dd class="text-ink-muted">
					Every bin is cleared, and categories are given bins as pieces arrive.
				</dd>
			</div>
			<div class="px-3 py-2">
				<dt class="font-medium text-ink">Pre-assign from rules</dt>
				<dd class="text-ink-muted">
					Bins are filled in the order of the profile's rules: rule 1 in bin 1, rule 2 in bin 2, and
					so on.
				</dd>
			</div>
		</dl>
	{/if}
	{#snippet footer()}
		{@render switchChoices((mode) => void confirmApplyRecentProfile(mode), cancelApplyRecentProfile)}
	{/snippet}
</Modal>

<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import ProfileApplyModal from '$lib/components/profiles/ProfileApplyModal.svelte';
	import ProfileCard from '$lib/components/profiles/ProfileCard.svelte';
	import ProfileDetailsModal from '$lib/components/profiles/ProfileDetailsModal.svelte';
	import ProfilePagination from '$lib/components/profiles/ProfilePagination.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import {
		applyProfile,
		fetchLibrary,
		fetchProfileDetail,
		reloadRuntimeProfile as callReloadRuntime,
		visibleVersions
	} from '$lib/sorting-profiles/api';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import type {
		HiveTargetLibrary,
		PendingProfileApply,
		SortingProfileCardEntry,
		SortingProfileDetail,
		SortingProfileLibraryResponse,
		SortingProfileSummary
	} from '$lib/sorting-profiles/types';
	import { RotateCw } from 'lucide-svelte';
	import { onMount } from 'svelte';

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

	async function loadLibrary() {
		loading = true;
		error = null;
		try {
			library = await fetchLibrary(baseUrl());
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
			const detail = await fetchProfileDetail(baseUrl(), targetId, profile.id);
			detailCache = { ...detailCache, [key]: detail };

			// Pre-select version: for the active profile, pick the latest version
			// (which may be newer); for others, also pick the latest.
			const versions = visibleVersions(detail);
			let preselect = versions[0]?.id ?? '';
			if (library?.sync_state?.profile_id === profile.id && library.sync_state.version_id) {
				preselect = versions[0]?.id ?? library.sync_state.version_id;
			}
			selectedVersionIds = { ...selectedVersionIds, [key]: preselect };

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
			const detail = await fetchProfileDetail(baseUrl(), targetId, profile.id, versionId);
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

	async function requestApplyProfile(target: HiveTargetLibrary, profile: SortingProfileSummary) {
		await requestApplyProfileVersion(target, profile, null);
	}

	async function requestApplyProfileVersion(
		target: HiveTargetLibrary,
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
			const payload = await applyProfile(baseUrl(), applyRequest);
			if (payload.activation_error) {
				success = `Using ${applyRequest.profile_name} locally. Bin assignments were reset.`;
				warning = `Hive activation could not be confirmed: ${payload.activation_error}`;
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

	async function reloadRuntime() {
		reloadingRuntime = true;
		error = null;
		success = null;
		warning = null;
		try {
			await callReloadRuntime(baseUrl());
			await sortingProfileStore.reload(baseUrl());
			await loadLibrary();
			success = 'Reloaded the current sorting profile from disk.';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to reload sorting profile';
		} finally {
			reloadingRuntime = false;
		}
	}

	function normalizedSearchQuery(): string {
		return searchQuery.trim().toLowerCase();
	}

	function searchableProfileText(profile: SortingProfileSummary): string {
		const ruleBits = (profile.latest_published_version ?? profile.latest_version)?.rules_summary
			?.filter((rule) => !rule.disabled)
			.flatMap((rule) => [
				rule.name,
				rule.set_num,
				rule.set_meta?.name,
				rule.set_meta?.year != null ? String(rule.set_meta.year) : null
			]) ?? [];
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

	function targetErrors(): HiveTargetLibrary[] {
		if (!library) return [];
		return library.targets.filter((target) => Boolean(target.error));
	}

	function selectedVersionIdFor(targetId: string, profileId: string): string | null {
		return selectedVersionIds[detailKey(targetId, profileId)] ?? null;
	}

	// ─── Details-modal derivations ──────────────────────────────────────

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
		if (summary && (!selectedVersionId || summary.current_version?.id === selectedVersionId)) {
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

	async function openProfileDetails(target: HiveTargetLibrary, profile: SortingProfileSummary) {
		const key = detailKey(target.id, profile.id);
		const summary = detailCache[key] ?? (await loadProfileDetail(target.id, profile));
		if (!summary) {
			error = detailErrors[key] ?? 'Failed to load profile details.';
			return;
		}
		const versionId = selectedVersionIds[key] || visibleVersions(summary)[0]?.id || '';
		if (versionId) {
			selectedVersionIds = { ...selectedVersionIds, [key]: versionId };
		}
		detailsModalTargetId = target.id;
		detailsModalProfileId = profile.id;
		detailsModalOpen = true;
		if (versionId) {
			await loadProfileVersionDetail(target.id, profile, versionId);
		}
	}

	async function handleVersionSelection(
		target: HiveTargetLibrary,
		profile: SortingProfileSummary,
		versionId: string
	) {
		const key = detailKey(target.id, profile.id);
		selectedVersionIds = { ...selectedVersionIds, [key]: versionId };
		if (
			detailsModalOpen &&
			detailsModalTargetId === target.id &&
			detailsModalProfileId === profile.id &&
			versionId
		) {
			await loadProfileVersionDetail(target.id, profile, versionId);
		}
	}

	async function handleDetailsModalVersionChange(versionId: string) {
		const target = library?.targets.find((item) => item.id === detailsModalTargetId);
		const profile = target?.profiles.find((item) => item.id === detailsModalProfileId);
		if (!target || !profile) return;
		await handleVersionSelection(target, profile, versionId);
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
					onclick={reloadRuntime}
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
		{:else if library.targets.length === 0}
			<p class="text-sm text-text-muted">
				No Hive targets are configured on this machine right now.
				{#if library.local_profile.name}
					The active local profile above still works.
				{/if}
				Add one in <a href="/settings" class="underline hover:text-text">Settings</a>.
			</p>
		{:else}
			{#if normalizedSearchQuery() && filteredProfileEntries().length === 0}
				<div class="border border-border bg-surface px-4 py-6 text-center text-sm text-text-muted">
					No profiles match “{searchQuery.trim()}”.
				</div>
			{/if}

			{#if targetErrors().length > 0}
				<div class="mb-4 space-y-2">
					{#each targetErrors() as target}
						<div
							class="border border-[#D01012] bg-[#D01012]/10 px-3 py-2 text-sm text-[#D01012] dark:text-red-400"
						>
							{target.name}: {target.error}
						</div>
					{/each}
				</div>
			{/if}

			{#if filteredProfileEntries().length > 0}
				<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
					{#each paginatedProfileEntries() as entry}
						{@const key = detailKey(entry.target.id, entry.profile.id)}
						<ProfileCard
							target={entry.target}
							profile={entry.profile}
							detail={detailCache[key]}
							detailError={detailErrors[key]}
							syncState={library.sync_state}
							selectedVersionId={selectedVersionIds[key] ?? null}
							applyingKey={applyingKey}
							cardKey={key}
							openVersionMenuKey={openVersionMenuKey}
							onOpenDetails={() => void openProfileDetails(entry.target, entry.profile)}
							onApply={() => void requestApplyProfile(entry.target, entry.profile)}
							onApplyVersion={(versionId) =>
								void requestApplyProfileVersion(entry.target, entry.profile, versionId)}
							onToggleVersionMenu={() => toggleVersionMenu(key)}
						/>
					{/each}
				</div>

				<ProfilePagination
					pageSize={pageSize}
					pageSizeOptions={PROFILE_PAGE_SIZE_OPTIONS}
					currentPage={currentListPage()}
					totalPages={totalPages()}
					summary={paginationSummary()}
					visiblePageNumbers={visiblePageNumbers()}
					onPageSizeChange={(size) => {
						pageSize = size;
						currentPage = 1;
					}}
					onPageChange={(page) => {
						currentPage = Math.min(Math.max(page, 1), totalPages());
					}}
				/>
			{/if}
		{/if}
	</div>

	<ProfileApplyModal
		bind:open={applyConfirmOpen}
		pending={pendingApply}
		onConfirm={() => void confirmApplyProfile()}
		onCancel={() => {
			applyConfirmOpen = false;
			pendingApply = null;
		}}
	/>

	<ProfileDetailsModal
		bind:open={detailsModalOpen}
		summary={activeDetailsModalSummary()}
		detail={activeDetailsModalDetail()}
		loading={activeDetailsModalLoading()}
		error={activeDetailsModalError()}
		selectedVersionId={detailsModalTargetId && detailsModalProfileId
			? selectedVersionIdFor(detailsModalTargetId, detailsModalProfileId)
			: null}
		onVersionChange={(versionId) => void handleDetailsModalVersionChange(versionId)}
	/>
</div>

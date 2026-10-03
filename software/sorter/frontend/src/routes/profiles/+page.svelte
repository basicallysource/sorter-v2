<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import ActiveProfileBinsModal from '$lib/components/profiles/ActiveProfileBinsModal.svelte';
	import ActiveProfilePanel from '$lib/components/profiles/ActiveProfilePanel.svelte';
	import ProfileApplyModal from '$lib/components/profiles/ProfileApplyModal.svelte';
	import BsxSection from '$lib/components/profiles/BsxSection.svelte';
	import LocalProfileCard from '$lib/components/profiles/LocalProfileCard.svelte';
	import ProfileCard from '$lib/components/profiles/ProfileCard.svelte';
	import ProfileCardSkeleton from '$lib/components/profiles/ProfileCardSkeleton.svelte';
	import ProfileDetailsModal from '$lib/components/profiles/ProfileDetailsModal.svelte';
	import ProfilePagination from '$lib/components/profiles/ProfilePagination.svelte';
	import RouteCheckPanel from '$lib/components/profiles/RouteCheckPanel.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import {
		applyLocalProfile,
		applyProfile,
		deleteLocalProfile,
		fetchLocalLibrary,
		fetchLocalProfileMeta,
		fetchTargetLibrary,
		fetchProfileDetail,
		reloadRuntimeProfile as callReloadRuntime,
		uploadLocalProfile,
		visibleVersions
	} from '$lib/sorting-profiles/api';
	import { newerVersion, ownFirst } from '$lib/sorting-profiles/bins';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import type {
		HiveTargetLibrary,
		LocalSortingProfile,
		PendingProfileApply,
		SortingProfileCardEntry,
		SortingProfileDetail,
		SortingProfileLibraryResponse,
		SortingProfileSummary
	} from '$lib/sorting-profiles/types';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import Upload from '@lucide/svelte/icons/upload';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();
	const PROFILE_PAGE_SIZE_OPTIONS = [12, 24, 48] as const;

	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let warning = $state<string | null>(null);
	let library = $state<SortingProfileLibraryResponse | null>(null);
	let targetLoading = $state<Record<string, boolean>>({});
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
	let fileInput = $state<HTMLInputElement | null>(null);
	let uploading = $state(false);
	let pendingLocal = $state<LocalSortingProfile | null>(null);
	let localApplyOpen = $state(false);
	let localApplyingFilename = $state<string | null>(null);
	let deletingFilename = $state<string | null>(null);
	let pendingDelete = $state<LocalSortingProfile | null>(null);
	let localDeleteOpen = $state(false);
	let binsModalOpen = $state(false);
	let metadataLoading = $state(false);
	let metadataError = $state<string | null>(null);
	let updating = $state(false);

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function detailKey(targetId: string, profileId: string) {
		return `${targetId}:${profileId}`;
	}

	function versionDetailKey(targetId: string, profileId: string, versionId: string) {
		return `${targetId}:${profileId}:${versionId}`;
	}

	// Tier 1 — fast local read: target metadata, active sync state, and local
	// profile filenames. No Hive network and no multi-MB parse, so this returns
	// in milliseconds and the page can skeleton everything at once. Local
	// profile counts/names arrive later via loadLocalMetas().
	async function loadLocal() {
		error = null;
		try {
			const local = await fetchLocalLibrary(baseUrl());
			// Merge into existing state so a background refresh doesn't wipe
			// already-loaded target profiles or local-profile metadata.
			const prevTargets = new Map((library?.targets ?? []).map((t) => [t.id, t]));
			const prevLocals = new Map((library?.local_profiles ?? []).map((p) => [p.filename, p]));
			library = {
				...local,
				targets: local.targets.map((meta) => {
					const existing = prevTargets.get(meta.id);
					return existing && existing.profiles.length > 0
						? {
								...meta,
								profiles: existing.profiles,
								assignment: existing.assignment,
								error: existing.error
							}
						: meta;
				}),
				local_profiles: local.local_profiles.map((lp) => {
					const prev = prevLocals.get(lp.filename);
					// Keep loaded counts/name if the file is unchanged (same mtime).
					return prev && prev.rule_count != null && prev.updated_at === lp.updated_at
						? {
								...lp,
								name: prev.name,
								description: prev.description,
								profile_type: prev.profile_type,
								rule_count: prev.rule_count,
								category_count: prev.category_count,
								part_count: prev.part_count,
								artifact_hash: prev.artifact_hash
							}
						: lp;
				})
			};
			void loadLocalMetas();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load sorting profile library';
		}
	}

	// Tier 1b — fill in local profile names/counts, one cheap (cached) request
	// per file that still lacks them. Runs in parallel; cards show a placeholder
	// until their meta lands.
	async function loadLocalMetas() {
		if (!library) return;
		const pending = library.local_profiles.filter((p) => p.rule_count == null && !p.error);
		await Promise.all(
			pending.map(async (profile) => {
				try {
					const meta = await fetchLocalProfileMeta(baseUrl(), profile.filename);
					if (!library) return;
					library = {
						...library,
						local_profiles: library.local_profiles.map((p) =>
							p.filename === profile.filename ? { ...p, ...meta } : p
						)
					};
				} catch {
					// Leave as-is; the card falls back to the filename.
				}
			})
		);
	}

	// Tier 2 — one target's Hive profiles. Called per enabled target in
	// parallel; updates just that target's slice as it resolves.
	async function loadTarget(targetId: string) {
		targetLoading = { ...targetLoading, [targetId]: true };
		try {
			const result = await fetchTargetLibrary(baseUrl(), targetId);
			if (library) {
				library = {
					...library,
					targets: library.targets.map((t) => (t.id === targetId ? { ...t, ...result } : t))
				};
			}
			forgetChangedDetails(targetId, result.profiles);
		} catch (e: unknown) {
			const message = e instanceof Error ? e.message : 'Failed to load profiles';
			if (library) {
				library = {
					...library,
					targets: library.targets.map((t) => (t.id === targetId ? { ...t, error: message } : t))
				};
			}
		} finally {
			const { [targetId]: _ignore, ...rest } = targetLoading;
			targetLoading = rest;
		}
	}

	// A profile that has a new version since its versions were loaded (an assistant
	// saves them often) is loaded again, so a card never activates an old one.
	function forgetChangedDetails(targetId: string, profiles: SortingProfileSummary[]) {
		for (const profile of profiles) {
			const key = detailKey(targetId, profile.id);
			const known = detailCache[key];
			if (
				!known ||
				(known.latest_version_number === profile.latest_version_number &&
					known.latest_published_version_number === profile.latest_published_version_number)
			) {
				continue;
			}
			const { [key]: _detail, ...details } = detailCache;
			detailCache = details;
			const { [key]: _chosen, ...chosen } = selectedVersionIds;
			selectedVersionIds = chosen;
			versionDetailCache = Object.fromEntries(
				Object.entries(versionDetailCache).filter(([k]) => !k.startsWith(`${key}:`))
			);
		}
	}

	function loadAllTargets() {
		if (!library) return;
		for (const target of library.targets) {
			if (target.enabled) void loadTarget(target.id);
		}
	}

	// Full refresh: fast local first, then fan out the Hive fetches.
	async function loadLibrary() {
		await loadLocal();
		loadAllTargets();
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

	// ─── The profile this machine runs ──────────────────────────────────

	const hasActiveProfile = $derived(
		Boolean(library?.local_profile?.path || library?.sync_state?.profile_name)
	);

	// The running profile, when it came from Hive and Hive has a newer version:
	// the owner's own newest, anyone else's newest published.
	const activeUpdate = $derived.by(() => {
		const sync = library?.sync_state;
		if (!library || !sync || sync.source === 'local' || !sync.profile_id || !sync.target_id) {
			return null;
		}
		const target = library.targets.find((t) => t.id === sync.target_id);
		const profile = target?.profiles.find((p) => p.id === sync.profile_id);
		if (!target || !profile) return null;
		const latest = newerVersion(profile, sync.version_number);
		return latest == null ? null : { target, profile, latest, current: sync.version_number ?? 0 };
	});

	async function openActiveBins() {
		binsModalOpen = true;
		metadataLoading = true;
		metadataError = null;
		try {
			await sortingProfileStore.reload(baseUrl());
		} catch (e: unknown) {
			metadataError = e instanceof Error ? e.message : 'Could not load the bins of this profile.';
		} finally {
			metadataLoading = false;
		}
	}

	// Put Hive's newer version of the running profile in place. The bins keep what
	// is in them: nothing is reset, unlike choosing another profile.
	async function updateActiveProfile() {
		const info = activeUpdate;
		if (!info) return;
		updating = true;
		error = null;
		success = null;
		warning = null;
		try {
			const key = detailKey(info.target.id, info.profile.id);
			// The versions are read again: an assistant may have saved this one since.
			const detail = await fetchProfileDetail(baseUrl(), info.target.id, info.profile.id);
			detailCache = { ...detailCache, [key]: detail };
			const versions = visibleVersions(detail);
			const version = versions.find((v) => v.version_number === info.latest) ?? versions[0];
			if (!version) throw new Error('No version available for this profile.');
			const payload = await applyProfile(
				baseUrl(),
				{
					target_id: info.target.id,
					profile_id: info.profile.id,
					profile_name: info.profile.name,
					version_id: version.id,
					version_number: version.version_number ?? null,
					version_label: version.label ?? null
				},
				{ keepBins: true }
			);
			success = `Updated ${info.profile.name} to v${version.version_number}. The bins kept what was in them.`;
			if (payload.activation_error) {
				warning = `Hive activation could not be confirmed: ${payload.activation_error}`;
			}
			await sortingProfileStore.reload(baseUrl());
			await loadLibrary();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update the sorting profile';
		} finally {
			updating = false;
		}
	}

	function localProfiles(): LocalSortingProfile[] {
		return library?.local_profiles ?? [];
	}

	async function handleUploadFile(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		uploading = true;
		error = null;
		success = null;
		warning = null;
		try {
			const text = await file.text();
			let artifact: unknown;
			try {
				artifact = JSON.parse(text);
			} catch {
				throw new Error('That file is not valid JSON.');
			}
			const fallbackName = file.name.replace(/\.json$/i, '');
			const artifactName =
				artifact && typeof artifact === 'object' && 'name' in artifact
					? (artifact as { name?: string }).name
					: null;
			await uploadLocalProfile(baseUrl(), artifact, artifactName || fallbackName);
			await loadLibrary();
			success = `Uploaded ${artifactName || fallbackName}.`;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to upload sorting profile';
		} finally {
			uploading = false;
		}
	}

	function requestApplyLocal(profile: LocalSortingProfile) {
		pendingLocal = profile;
		localApplyOpen = true;
	}

	async function confirmApplyLocal(mode: 'empty' | 'rules') {
		const profile = pendingLocal;
		if (!profile) return;
		localApplyOpen = false;
		localApplyingFilename = profile.filename;
		error = null;
		success = null;
		warning = null;
		try {
			const payload = await applyLocalProfile(baseUrl(), profile.filename, mode);
			const label = profile.name || profile.filename;
			const preassigned = payload?.preassigned_count as number | undefined;
			if (mode === 'rules' && preassigned) {
				success = `Using ${label}. Pre-assigned ${preassigned} bin${preassigned === 1 ? '' : 's'}.`;
			} else {
				success = `Using ${label} on this machine. Bin assignments were reset.`;
			}
			await sortingProfileStore.reload(baseUrl());
			await loadLibrary();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to apply local sorting profile';
		} finally {
			localApplyingFilename = null;
		}
	}

	async function confirmDeleteLocal() {
		const profile = pendingDelete;
		if (!profile) return;
		localDeleteOpen = false;
		deletingFilename = profile.filename;
		error = null;
		try {
			await deleteLocalProfile(baseUrl(), profile.filename);
			await loadLibrary();
			success = `Deleted ${profile.name || profile.filename}.`;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete local sorting profile';
		} finally {
			deletingFilename = null;
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
		const ruleBits =
			(profile.latest_published_version ?? profile.latest_version)?.rules_summary
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
			profile.is_default ? 'Hive default' : null,
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
		// The person's own profiles first, then Hive's defaults.
		return ownFirst(
			library.targets.flatMap((target) => target.profiles.map((profile) => ({ target, profile })))
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

	// True while any enabled target's Hive fetch is still in flight — drives the
	// skeleton cards. Suppressed during search so placeholders don't masquerade
	// as unfiltered results.
	function showTargetSkeletons(): boolean {
		return Object.keys(targetLoading).length > 0 && !normalizedSearchQuery();
	}

	function skeletonCardCount(): number {
		return filteredProfileEntries().length > 0 ? 3 : 6;
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
		return key ? (detailCache[key] ?? null) : null;
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
		return key ? (detailErrors[key] ?? null) : null;
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

	/** Auto-load profile detail for the currently visible cards, in parallel. */
	function autoLoadVisibleDetails() {
		if (!library) return;
		for (const entry of paginatedProfileEntries()) {
			const target = entry.target;
			const profile = entry.profile;
			const key = detailKey(target.id, profile.id);
			if (!detailCache[key] && !detailErrors[key] && !loadingDetailKeys[key]) {
				// Fire-and-forget; each card shows its own loading state until
				// its detail lands. Errors are surfaced per-card via detailErrors.
				void loadProfileDetail(target.id, profile);
			}
		}
	}

	$effect(() => {
		const currentUrl = manager.selectedMachine?.url ?? '';
		if (currentUrl === lastMachineUrl) return;
		lastMachineUrl = currentUrl;
		library = null;
		targetLoading = {};
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
		void sortingProfileStore.load(baseUrl()).catch(() => {});
	});

	// Auto-load versions whenever the visible card set changes.
	$effect(() => {
		if (library && library.targets.length > 0) {
			autoLoadVisibleDetails();
		}
	});

	onMount(() => {
		void loadLibrary();
		void sortingProfileStore.load(baseUrl()).catch(() => {});
		// Poll the cheap local tier often (active-profile + local-profile
		// changes); refresh the expensive Hive tier on a slower cadence to
		// spare the CPU-bound backend.
		const localPoll = setInterval(() => void loadLocal(), 10000);
		const hivePoll = setInterval(() => loadAllTargets(), 60000);
		return () => {
			clearInterval(localPoll);
			clearInterval(hivePoll);
		};
	});
</script>

<svelte:head><title>Sorting profiles - Sorter</title></svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-[1500px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader title="Sorting profiles" description="The rules that decide which bin each piece goes to.">
			{#snippet actions()}
				<Input
					type="search"
					aria-label="Search profiles"
					placeholder="Search profiles, sets, tags, owners"
					class="w-72 max-w-full"
					bind:value={searchQuery}
					oninput={() => (currentPage = 1)}
				/>
				<Button
					icon={RotateCw}
					label="Reload the runtime profile from disk"
					loading={reloadingRuntime}
					onclick={reloadRuntime}
				/>
			{/snippet}
		</PageHeader>

		{#if success}<Alert tone="success">{success}</Alert>{/if}
		{#if warning}<Alert tone="warning">{warning}</Alert>{/if}
		{#if error}<Alert tone="danger">{error}</Alert>{/if}

		<input
			bind:this={fileInput}
			type="file"
			accept="application/json,.json"
			class="hidden"
			onchange={handleUploadFile}
		/>

		{#if hasActiveProfile}
			<div class="grid items-start gap-(--gap-panels) lg:grid-cols-2">
				<ActiveProfilePanel
					syncState={library?.sync_state ?? null}
					localProfile={library?.local_profile ?? null}
					metadata={sortingProfileStore.data}
					update={activeUpdate ? { latest: activeUpdate.latest, current: activeUpdate.current } : null}
					{updating}
					onUpdate={() => void updateActiveProfile()}
					onOpenBins={() => void openActiveBins()}
				/>
				<RouteCheckPanel baseUrl={baseUrl()} />
			</div>
		{/if}

		<BsxSection baseUrl={baseUrl()} />

		<section class="flex flex-col gap-3">
			<div class="flex items-center justify-between gap-3">
				<h2 class="text-base font-semibold text-ink">Local profiles</h2>
				<Button size="sm" icon={Upload} loading={uploading} onclick={() => fileInput?.click()}>
					Upload JSON
				</Button>
			</div>

			{#if library == null}
				<div class="grid grid-cols-1 gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-3">
					{#each Array(2) as _}
						<ProfileCardSkeleton />
					{/each}
				</div>
			{:else if localProfiles().length === 0}
				<EmptyState title="No local profiles are saved yet">
					Upload a profile JSON to keep it on this machine.
				</EmptyState>
			{:else}
				<div class="grid grid-cols-1 gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-3">
					{#each localProfiles() as profile}
						<LocalProfileCard
							{profile}
							activating={localApplyingFilename === profile.filename}
							deleting={deletingFilename === profile.filename}
							onActivate={() => requestApplyLocal(profile)}
							onOpenBins={() => void openActiveBins()}
							onDelete={() => {
								pendingDelete = profile;
								localDeleteOpen = true;
							}}
						/>
					{/each}
				</div>
			{/if}
		</section>

		<section class="flex flex-col gap-3">
			<h2 class="text-base font-semibold text-ink">Profiles from Hive</h2>

			{#if library == null}
				{#if !error}
					<div class="grid grid-cols-1 gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-3">
						{#each Array(6) as _}
							<ProfileCardSkeleton />
						{/each}
					</div>
				{/if}
			{:else if library.targets.length === 0}
				<EmptyState title="No Hive targets are configured on this machine">
					{#if library.local_profile.name}The active local profile above still works. {/if}Add one in
					<a href="/settings" class="text-primary-ink hover:underline">Settings</a>.
				</EmptyState>
			{:else}
				{#if normalizedSearchQuery() && filteredProfileEntries().length === 0}
					<EmptyState title="No profiles match “{searchQuery.trim()}”" />
				{/if}

				{#each targetErrors() as target}
					<Alert tone="danger">{target.name}: {target.error}</Alert>
				{/each}

				{#if filteredProfileEntries().length > 0 || showTargetSkeletons()}
					<div class="grid grid-cols-1 gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-3">
						{#each paginatedProfileEntries() as entry}
							{@const key = detailKey(entry.target.id, entry.profile.id)}
							<ProfileCard
								target={entry.target}
								profile={entry.profile}
								detail={detailCache[key]}
								detailError={detailErrors[key]}
								syncState={library.sync_state}
								selectedVersionId={selectedVersionIds[key] ?? null}
								{applyingKey}
								cardKey={key}
								onOpenDetails={() => void openProfileDetails(entry.target, entry.profile)}
								onApply={() => void requestApplyProfile(entry.target, entry.profile)}
								onApplyVersion={(versionId) =>
									void requestApplyProfileVersion(entry.target, entry.profile, versionId)}
							/>
						{/each}
						{#if showTargetSkeletons()}
							{#each Array(skeletonCardCount()) as _}
								<ProfileCardSkeleton />
							{/each}
						{/if}
					</div>

					{#if filteredProfileEntries().length > 0}
						<ProfilePagination
							{pageSize}
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
			{/if}
		</section>
	</div>
</AppShell>

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

<ActiveProfileBinsModal
	bind:open={binsModalOpen}
	metadata={sortingProfileStore.data}
	loading={metadataLoading}
	error={metadataError}
/>

<Modal bind:open={localApplyOpen} title="Activate the local profile">
	{#if pendingLocal !== null}
		{@const profile = pendingLocal}
		<div class="flex flex-col gap-4">
			<p>
				Activate <span class="font-semibold">{profile.name || profile.filename}</span>? Choose how the bins
				start.
			</p>
			<dl class="flex flex-col gap-2 rounded-control bg-well p-3 text-ink-muted">
				<div>
					<dt class="inline font-medium text-ink">Reset (dynamic):</dt>
					<dd class="inline">clear every bin; categories are assigned as pieces arrive.</dd>
				</div>
				<div>
					<dt class="inline font-medium text-ink">Pre-assign (rule order):</dt>
					<dd class="inline">seed the bins in the order of the profile's rules.</dd>
				</div>
			</dl>
		</div>
	{/if}
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (localApplyOpen = false)}>Cancel</Button>
		<Button onclick={() => void confirmApplyLocal('empty')}>Reset the bins</Button>
		<Button variant="primary" onclick={() => void confirmApplyLocal('rules')}>
			Pre-assign from the rules
		</Button>
	{/snippet}
</Modal>

<Modal bind:open={localDeleteOpen} title="Delete the local profile" size="sm">
	{#if pendingDelete !== null}
		{@const profile = pendingDelete}
		<p>
			Delete <span class="font-semibold">{profile.name || profile.filename}</span> from this machine? This
			removes the saved JSON file.
		</p>
	{/if}
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (localDeleteOpen = false)}>Cancel</Button>
		<Button variant="danger" onclick={() => void confirmDeleteLocal()}>Delete profile</Button>
	{/snippet}
</Modal>

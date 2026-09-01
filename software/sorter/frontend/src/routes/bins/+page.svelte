<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import BinDetailsModal from '$lib/components/bins/BinDetailsModal.svelte';
	import BinLayoutSection from '$lib/components/bins/BinLayoutSection.svelte';
	import BinsHeaderActions from '$lib/components/bins/BinsHeaderActions.svelte';
	import BinSearchBar from '$lib/components/bins/BinSearchBar.svelte';
	import ColumnsPanel from '$lib/components/bins/ColumnsPanel.svelte';
	import DiscardBinCard from '$lib/components/bins/DiscardBinCard.svelte';
	import LayerPanel from '$lib/components/bins/LayerPanel.svelte';
	import { categoryLabel } from '$lib/components/bins/pieces';
	import SnapshotsModal from '$lib/components/bins/SnapshotsModal.svelte';
	import type { BinContents, BinInfo, LayerInfo, SetMeta, SetProgressSummary } from '$lib/components/bins/types';
	import { Skeleton, ToggleSwitch } from '$lib/components/primitives';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { bricklinkParts } from '$lib/stores/bricklinkParts.svelte';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	const manager = getMachinesContext();
	// Active profile (id/name) — bin layouts are scoped to it. Local profiles carry a
	// local_filename rather than a profile_id; either identifies the profile a layout ties to.
	const profileSync = $derived(
		(manager.selectedMachine?.sortingProfileStatus as { sync_state?: Record<string, unknown> } | null)
			?.sync_state ?? null
	);
	const activeProfileId = $derived(
		(profileSync?.profile_id as string | undefined) ??
			(profileSync?.local_filename as string | undefined) ??
			null
	);
	const activeProfileName = $derived((profileSync?.profile_name as string | undefined) ?? '');
	let activeBaseUrl = $state(baseUrl());

	type ClearingState = {
		endpoint: 'contents/clear' | 'categories/clear';
		scope: 'all' | 'layer' | 'bin';
		busyKey: string;
		layerIndex?: number;
		sectionIndex?: number;
		binIndex?: number;
	};

	let layers = $state<LayerInfo[]>([]);
	let currentAngle = $state<number | null>(null);
	let activeLayer = $state<number | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let movingTo = $state<string | null>(null);
	let homing = $state(false);
	let statusMsg = $state('');
	let clearingStates = $state<ClearingState[]>([]);
	let togglingLayerKey = $state<number | null>(null);
	let sectionBusyKey = $state<string | null>(null);
	let pointingSectionKey = $state<string | null>(null);
	let allowMultiCategory = $state(false);
	let savingMultiCategory = $state(false);
	let autoAssignBusy = $state(false);
	let autoAssignResult = $state<string | null>(null);
	let contentsByKey = $state<Record<string, BinContents>>({});
	let detailsOpen = $state(false);
	let detailsBin = $state<{ bin: BinInfo; layerIndex: number; contents: BinContents | null } | null>(null);
	let snapshotsOpen = $state(false);
	let niiBusyLayer = $state<number | null>(null);
	let setProgressByCategoryId = $state<Record<string, SetProgressSummary>>({});
	let searchQuery = $state('');

	const searchActive = $derived(searchQuery.trim().length > 0);

	// Client-side "find a part": matches bin number, assigned category label, and
	// the bin's grouped contents (part id, BrickLink part name, color name).
	function binMatchesSearch(layerIndex: number, bin: BinInfo): boolean {
		const query = searchQuery.trim().toLowerCase();
		if (!query) return true;
		if (String(bin.global_index + 1) === query) return true;
		if (categoryLabel(bin.category_ids).toLowerCase().includes(query)) return true;
		const contents = contentsForBin(layerIndex, bin);
		if (!contents) return false;
		for (const item of contents.items) {
			if (item.part_id && item.part_id.toLowerCase().includes(query)) return true;
			if (item.color_name && item.color_name.toLowerCase().includes(query)) return true;
			const partName = bricklinkParts.get(item.part_id)?.name;
			if (partName && partName.toLowerCase().includes(query)) return true;
		}
		return false;
	}

	const totalBinCount = $derived(layers.reduce((sum, layer) => sum + layer.bins.length, 0));

	const searchMatchCount = $derived.by((): number | null => {
		if (!searchActive) return null;
		let count = 0;
		for (const layer of layers) {
			for (const bin of layer.bins) {
				if (binMatchesSearch(layer.layer_index, bin)) count += 1;
			}
		}
		return count;
	});

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function binKey(layerIndex: number, sectionIndex: number, binIndex: number): string {
		return `${layerIndex}:${sectionIndex}:${binIndex}`;
	}

	function currentContentsCsvUrl(): string {
		return `${baseUrl()}/api/bins/contents/export.csv`;
	}

	async function loadLayout() {
		try {
			const res = await fetch(`${baseUrl()}/api/bins/layout`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			layers = data.layers ?? [];
			currentAngle = data.current_angle;
			activeLayer = data.active_layer;
			error = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load bin layout';
		} finally {
			loading = false;
		}
	}

	async function loadBinSettings() {
		try {
			const res = await fetch(`${baseUrl()}/api/bins/settings`);
			if (!res.ok) return;
			const data = await res.json();
			allowMultiCategory = Boolean(data.allow_multiple_categories_per_bin);
		} catch {
			// Keep last known setting on transient failures.
		}
	}

	async function setLayerNotInInventory(layerIndex: number, enabled: boolean) {
		niiBusyLayer = layerIndex;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/not-in-inventory/set`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ scope: 'layer', layer_index: layerIndex, enabled })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			await loadLayout();
			statusMsg = enabled
				? `Layer ${layerIndex + 1} is now a "not in inventory" layer.`
				: `Layer ${layerIndex + 1} is back to normal sorting.`;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update not-in-inventory mode';
		} finally {
			niiBusyLayer = null;
		}
	}

	async function runAutoAssign(overlap: boolean) {
		if (autoAssignBusy) return;
		autoAssignBusy = true;
		autoAssignResult = null;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/auto-assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ overlap })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			await loadLayout();
			if (data.assigned === 0) {
				autoAssignResult = data.message ?? 'Nothing to assign.';
			} else {
				autoAssignResult = `Assigned ${data.categories_ranked} categories across ${data.bins_used} bin${data.bins_used === 1 ? '' : 's'} from ${data.total_pieces} recent pieces${overlap ? ' (overlapping)' : ''}.`;
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Auto-assign failed';
		} finally {
			autoAssignBusy = false;
		}
	}

	async function toggleMultiCategory() {
		if (savingMultiCategory) return;
		savingMultiCategory = true;
		statusMsg = '';
		error = null;
		const next = !allowMultiCategory;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/settings`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ allow_multiple_categories_per_bin: next })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			allowMultiCategory = Boolean(data.allow_multiple_categories_per_bin);
			statusMsg = allowMultiCategory
				? 'Bins can now hold multiple categories once all bins are assigned.'
				: 'Bins will use a single category each.';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update setting';
		} finally {
			savingMultiCategory = false;
		}
	}

	async function loadSetProgress() {
		try {
			const res = await fetch(`${baseUrl()}/api/set-progress`);
			if (!res.ok) return;
			const data = await res.json();
			const sets = Array.isArray(data?.progress?.sets) ? data.progress.sets : [];
			const next: Record<string, SetProgressSummary> = {};
			for (const entry of sets) {
				if (!entry || typeof entry.id !== 'string') continue;
				next[entry.id] = {
					total_needed: Number(entry.total_needed) || 0,
					total_found: Number(entry.total_found) || 0,
					pct: Number(entry.pct) || 0
				};
			}
			setProgressByCategoryId = next;
		} catch {
			// Keep last known progress on transient failures.
		}
	}

	function binSetProgress(categoryIds: string[]): SetProgressSummary | null {
		if (!categoryIds || categoryIds.length !== 1) return null;
		return setProgressByCategoryId[categoryIds[0]] ?? null;
	}

	function applyBinsContents(bins: unknown) {
		const next: Record<string, BinContents> = {};
		for (const entry of Array.isArray(bins) ? bins : []) {
			if (!entry || typeof entry !== 'object' || typeof entry.bin_key !== 'string') continue;
			next[entry.bin_key] = entry as BinContents;
		}
		contentsByKey = next;
		// bricklinkParts is cached per part, so re-applying the full snapshot only
		// hits the (slow) BrickLink API for parts we haven't seen yet.
		for (const bin of Object.values(next)) {
			for (const item of bin.items) {
				if (item.part_id) void bricklinkParts.fetch(baseUrl(), item.part_id);
			}
		}
	}

	// Change token from /api/bins/contents/version. The heavy contents payload is
	// only fetched when this changes; direct loads reset it to null so the next
	// version tick re-syncs after mutations.
	let contentsVersion: string | null = null;
	let contentsLoaded = $state(false);

	async function loadBinContents() {
		contentsVersion = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/contents`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			applyBinsContents(data.bins);
			contentsLoaded = true;
		} catch {
			// Keep last known contents on transient failures.
		}
	}

	async function pollBinContentsVersion() {
		try {
			const res = await fetch(`${baseUrl()}/api/bins/contents/version`);
			if (!res.ok) return;
			const data = await res.json();
			const version = typeof data.version === 'string' ? data.version : null;
			if (version === null || version === contentsVersion) return;
			await loadBinContents();
			contentsVersion = version;
		} catch {
			// Retry on the next tick.
		}
	}

	function contentsForBin(layerIndex: number, bin: BinInfo): BinContents | null {
		return contentsByKey[binKey(layerIndex, bin.section_index, bin.bin_index)] ?? null;
	}

	async function moveToBin(layerIndex: number, sectionIndex: number, binIndex: number) {
		const key = `${layerIndex}-${sectionIndex}-${binIndex}`;
		if (movingTo) return;
		movingTo = key;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/move-to`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					layer_index: layerIndex,
					section_index: sectionIndex,
					bin_index: binIndex
				})
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			statusMsg = `Moved to ${data.target_angle}°`;
			activeLayer = layerIndex;
			currentAngle = data.target_angle;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Move failed';
		} finally {
			movingTo = null;
		}
	}

	async function homeChute() {
		if (homing || movingTo || hasAnyClearing() || togglingLayerKey !== null) return;
		homing = true;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/hardware-config/chute/calibrate/find-endstop`, {
				method: 'POST'
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			statusMsg = 'Chute homed successfully';
			await loadLayout();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Homing failed';
		} finally {
			homing = false;
		}
	}

	function isCurrentBin(bin: BinInfo): boolean {
		if (currentAngle === null) return false;
		return Math.abs(bin.angle - currentAngle) < 2;
	}

	function assignedSetMeta(categoryIds: string[]): SetMeta | null {
		if (!categoryIds || categoryIds.length !== 1) return null;
		const categoryId = categoryIds[0];
		const match = sortingProfileStore.data?.rules.find((rule) => {
			const candidate = rule as any;
			return candidate.id === categoryId && candidate.rule_type === 'set';
		}) as any;
		if (!match) return null;
		return {
			name: match.name,
			set_num: match.set_num,
			img_url: match.set_meta?.img_url
		};
	}

	function openBinDetails(layerIndex: number, bin: BinInfo) {
		detailsBin = { layerIndex, bin, contents: contentsForBin(layerIndex, bin) };
		detailsOpen = true;
	}

	function actionVerb(endpoint: 'contents/clear' | 'categories/clear'): string {
		return endpoint === 'contents/clear' ? 'Emptying' : 'Resetting';
	}

	function hasAnyClearing(): boolean {
		return clearingStates.length > 0;
	}

	function hasClearingKey(busyKey: string): boolean {
		return clearingStates.some((state) => state.busyKey === busyKey);
	}

	function activeGlobalClearing(): ClearingState | null {
		return clearingStates.find((state) => state.scope === 'all') ?? null;
	}

	function isGlobalClearing(): boolean {
		return activeGlobalClearing() !== null;
	}

	function isLayerClearing(layerIndex: number): boolean {
		return clearingStates.some(
			(state) => state.scope === 'layer' && state.layerIndex === layerIndex
		);
	}

	function isBinClearing(layerIndex: number, sectionIndex: number, binIndex: number): boolean {
		return clearingStates.some(
			(state) =>
				state.scope === 'bin' &&
				state.layerIndex === layerIndex &&
				state.sectionIndex === sectionIndex &&
				state.binIndex === binIndex
		);
	}

	function globalClearingTitle(): string {
		const state = activeGlobalClearing();
		if (!state) return '';
		return `${actionVerb(state.endpoint)} all bins…`;
	}

	function globalClearingDescription(): string {
		const state = activeGlobalClearing();
		if (!state) return '';
		return state.endpoint === 'contents/clear'
			? 'Updating the full machine state while keeping all current bin assignments in place.'
			: 'Clearing the full machine state and removing all current bin assignments.';
	}

	function layerClearingLabel(layerIndex: number): string {
		const state =
			clearingStates.find(
				(entry) => entry.scope === 'layer' && entry.layerIndex === layerIndex
			) ?? null;
		if (!state) return '';
		return `${actionVerb(state.endpoint)} layer ${layerIndex + 1}…`;
	}

	function binClearingLabel(layerIndex: number, sectionIndex: number, binIndex: number): string {
		const state =
			clearingStates.find(
				(entry) =>
					entry.scope === 'bin' &&
					entry.layerIndex === layerIndex &&
					entry.sectionIndex === sectionIndex &&
					entry.binIndex === binIndex
			) ?? null;
		if (!state) return '';
		return state.endpoint === 'contents/clear' ? 'Emptying bin…' : 'Resetting bin…';
	}

	async function runBinAction(
		endpoint: 'contents/clear' | 'categories/clear',
		scope: 'all' | 'layer' | 'bin',
		payload: { layer_index?: number; section_index?: number; bin_index?: number },
		confirmMessage: string,
		busyKey: string
	) {
		if (movingTo || homing || togglingLayerKey !== null || hasClearingKey(busyKey)) return;
		if (scope === 'all' ? hasAnyClearing() : isGlobalClearing()) return;
		if (!window.confirm(confirmMessage)) return;

		const nextState: ClearingState = {
			endpoint,
			scope,
			busyKey,
			layerIndex: payload.layer_index,
			sectionIndex: payload.section_index,
			binIndex: payload.bin_index
		};
		clearingStates = [...clearingStates, nextState];
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/${endpoint}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ scope, ...payload })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			statusMsg = data?.message ?? 'Bin assignments updated.';
			await loadLayout();
			await loadBinContents();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update bins';
		} finally {
			clearingStates = clearingStates.filter((state) => state.busyKey !== busyKey);
		}
	}

	// Dedicated full-reset path (layer or whole machine). The backend clears
	// assignments + contents in one call and returns the fresh layout + contents,
	// so we update state directly instead of firing extra GET round-trips.
	async function runBinReset(
		scope: 'all' | 'layer',
		layerIndex: number | undefined,
		confirmMessage: string,
		busyKey: string
	) {
		if (movingTo || homing || togglingLayerKey !== null || hasClearingKey(busyKey)) return;
		if (scope === 'all' ? hasAnyClearing() : isGlobalClearing()) return;
		if (!window.confirm(confirmMessage)) return;

		clearingStates = [
			...clearingStates,
			{ endpoint: 'categories/clear', scope, busyKey, layerIndex }
		];
		statusMsg = '';
		error = null;
		try {
			const url =
				scope === 'all'
					? `${baseUrl()}/api/bins/reset/machine`
					: `${baseUrl()}/api/bins/reset/layer/${layerIndex}`;
			const res = await fetch(url, { method: 'POST' });
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			statusMsg = data?.message ?? 'Bins reset.';
			if (data.layout) {
				layers = data.layout.layers ?? layers;
				currentAngle = data.layout.current_angle ?? null;
				activeLayer = data.layout.active_layer ?? null;
			}
			applyBinsContents(data.bins);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to reset bins';
		} finally {
			clearingStates = clearingStates.filter((state) => state.busyKey !== busyKey);
		}
	}

	async function toggleLayerEnabled(layerIndex: number, enabled: boolean) {
		if (movingTo || homing || hasAnyClearing() || togglingLayerKey !== null) return;
		togglingLayerKey = layerIndex;
		statusMsg = '';
		error = null;
		try {
			const payloadLayers = layers.map((layer) => ({
				bin_count: layer.bin_count,
				enabled: layer.layer_index === layerIndex ? enabled : layer.enabled,
				max_pieces_per_bin: layer.max_pieces_per_bin
			}));
			const res = await fetch(`${baseUrl()}/api/hardware-config/storage-layers`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ layers: payloadLayers })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			statusMsg = data?.message ?? `Layer ${layerIndex + 1} updated.`;
			await loadLayout();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update layer status';
		} finally {
			togglingLayerKey = null;
		}
	}

	function sectionEnabled(layer: LayerInfo, sectionIndex: number): boolean {
		return layer.section_enabled?.[sectionIndex] ?? true;
	}

	// A column (same section index across every layer) is "on" only when every
	// layer has that section enabled.
	function columnEnabled(sectionIndex: number): boolean {
		return layers.every((layer) => sectionEnabled(layer, sectionIndex));
	}

	function maxSectionCount(): number {
		return layers.reduce((max, layer) => Math.max(max, layer.section_count ?? 0), 0);
	}

	async function setSectionEnabled(
		scope: 'section' | 'column' | 'all',
		enabled: boolean,
		opts: { layer_index?: number; section_index?: number },
		busyKey: string
	) {
		if (movingTo || homing || hasAnyClearing() || sectionBusyKey !== null) return;
		sectionBusyKey = busyKey;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/sections/enabled`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ scope, enabled, ...opts })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			if (data.layout?.layers) {
				layers = data.layout.layers;
				currentAngle = data.layout.current_angle ?? currentAngle;
				activeLayer = data.layout.active_layer ?? activeLayer;
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update section status';
		} finally {
			sectionBusyKey = null;
		}
	}

	async function pointAtSection(sectionIndex: number) {
		const busyKey = `point-${sectionIndex}`;
		if (movingTo || homing || pointingSectionKey !== null) return;
		pointingSectionKey = busyKey;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/move-to-section`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ section_index: sectionIndex })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			statusMsg = `Pointing chute at section ${sectionIndex + 1} (${data.target_angle}°).`;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to point at section';
		} finally {
			pointingSectionKey = null;
		}
	}

	onMount(() => {
		void loadLayout();
		void loadBinContents();
		void loadSetProgress();
		void loadBinSettings();
		void sortingProfileStore.load(baseUrl()).catch(() => {});
		// Auto-update without hammering the machine: the fast tick fetches the
		// small layout payload (live chute angle) plus a tiny contents version
		// token — the heavy contents fetch only runs when that token changes.
		// Set progress moves to a slow multiple, and everything pauses while the
		// tab is hidden so a backgrounded tab can't saturate the machine's uplink.
		let tick = 0;
		const interval = setInterval(() => {
			if (document.hidden) return;
			tick += 1;
			void loadLayout();
			void pollBinContentsVersion();
			if (tick % 5 === 0) void loadSetProgress();
		}, 2000);
		const onVisibilityChange = () => {
			if (document.hidden) return;
			void loadLayout();
			void loadBinContents();
			void loadSetProgress();
		};
		document.addEventListener('visibilitychange', onVisibilityChange);
		return () => {
			clearInterval(interval);
			document.removeEventListener('visibilitychange', onVisibilityChange);
		};
	});

	$effect(() => {
		const nextBaseUrl = baseUrl();
		if (nextBaseUrl === activeBaseUrl) return;
		activeBaseUrl = nextBaseUrl;
		loading = true;
		error = null;
		statusMsg = '';
		layers = [];
		contentsByKey = {};
		contentsLoaded = false;
		contentsVersion = null;
		setProgressByCategoryId = {};
		detailsOpen = false;
		detailsBin = null;
		movingTo = null;
		homing = false;
		clearingStates = [];
		togglingLayerKey = null;
		searchQuery = '';
		void loadLayout();
		void loadBinContents();
		void loadSetProgress();
		void loadBinSettings();
		void sortingProfileStore.load(nextBaseUrl).catch(() => {});
	});

	// Keep the details modal pointed at fresh bin/contents objects as the live
	// polling replaces layers and contentsByKey.
	$effect(() => {
		const currentDetails = detailsBin;
		if (!currentDetails) return;
		const layer = layers.find((entry) => entry.layer_index === currentDetails.layerIndex);
		const bin = layer?.bins.find(
			(entry) =>
				entry.section_index === currentDetails.bin.section_index &&
				entry.bin_index === currentDetails.bin.bin_index
		);
		if (!bin) return;
		const contents = contentsForBin(currentDetails.layerIndex, bin);
		if (currentDetails.bin === bin && currentDetails.contents === contents) return;
		detailsBin = {
			layerIndex: currentDetails.layerIndex,
			bin,
			contents
		};
	});
</script>

<svelte:head><title>Sorter - Bins</title></svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	{#if isGlobalClearing()}
		<div class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4">
			<div class="w-full max-w-md border border-border bg-surface p-6 shadow-xl">
				<div class="flex items-start gap-4">
					<div class="flex h-10 w-10 items-center justify-center border border-border bg-bg">
						<Spinner size={18} class="text-primary" />
					</div>
					<div class="space-y-2">
						<h3 class="text-lg font-semibold text-text">{globalClearingTitle()}</h3>
						<p class="text-sm leading-6 text-text-muted">{globalClearingDescription()}</p>
						<p class="text-xs uppercase tracking-wide text-text-muted">Please wait while the sorter refreshes the bin state.</p>
					</div>
				</div>
			</div>
		</div>
	{/if}
	<div class="p-4 sm:p-6">
		<div class="mb-4 flex items-center justify-between gap-4">
			<div>
				<h2 class="text-xl font-bold text-text">Bin Grid</h2>
			</div>
			<BinsHeaderActions
				csvUrl={currentContentsCsvUrl()}
				{homing}
				emptyBusy={hasClearingKey('empty-all')}
				resetBusy={hasClearingKey('reset-all')}
				disabled={homing || !!movingTo || hasAnyClearing() || togglingLayerKey !== null}
				onSnapshots={() => (snapshotsOpen = true)}
				onHome={() => void homeChute()}
				onEmptyAll={() =>
					void runBinAction(
						'contents/clear',
						'all',
						{},
						'Please make sure all physical bins are empty first. This will mark every bin on the machine as emptied, but keep the current profile-to-bin assignments in place.',
						'empty-all'
					)}
				onResetAll={() =>
					void runBinReset(
						'all',
						undefined,
						'Please make sure all physical bins are empty first. This will remove every learned bin assignment on the machine and mark all bins as empty.',
						'reset-all'
					)}
			/>
		</div>

		<BinLayoutSection baseUrl={baseUrl()} profileId={activeProfileId} profileName={activeProfileName} />

		<div class="mb-4 flex items-center justify-between gap-4 border border-border bg-surface px-4 py-3">
			<div class="pr-4">
				<div class="text-sm font-medium text-text">Allow multiple categories per bin</div>
				<div class="mt-0.5 text-sm text-text-muted">
					When every bin already has an assignment, keep sorting new categories by
					combining them into existing bins (least-loaded first) instead of sending
					them to the discard passthrough.
				</div>
			</div>
			<ToggleSwitch
				checked={allowMultiCategory}
				label="Allow multiple categories per bin"
				disabled={savingMultiCategory}
				onToggle={() => void toggleMultiCategory()}
			/>
		</div>

		<div class="mb-4 border border-border bg-surface px-4 py-3">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="pr-4">
					<div class="text-sm font-medium text-text">Auto-assign bins</div>
					<div class="mt-0.5 text-sm text-text-muted">
						Ranks the active profile's categories by how many recently-sorted pieces
						hit them, then fills bins biggest-first — the larger bottom bins get the
						highest-volume categories. Overwrites current normal-bin assignments;
						not-in-inventory bins are left alone.
					</div>
				</div>
				<div class="flex items-center gap-2">
					<button
						type="button"
						onclick={() => void runAutoAssign(false)}
						disabled={autoAssignBusy}
						class="flex items-center gap-2 border border-border bg-surface px-3.5 py-2 text-sm font-medium text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
					>
						{autoAssignBusy ? 'Assigning…' : 'Auto-assign'}
					</button>
					<button
						type="button"
						onclick={() => void runAutoAssign(true)}
						disabled={autoAssignBusy}
						title="Pack every ranked category in, sharing bins once they run out"
						class="flex items-center gap-2 border border-border bg-surface px-3.5 py-2 text-sm font-medium text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
					>
						{autoAssignBusy ? 'Assigning…' : 'Auto-assign + overlap'}
					</button>
				</div>
			</div>
			{#if autoAssignResult}
				<div class="mt-2 text-sm text-text-muted">{autoAssignResult}</div>
			{/if}
		</div>

		{#if !loading && layers.length > 0 && maxSectionCount() > 0}
			<ColumnsPanel
				sectionCount={maxSectionCount()}
				{columnEnabled}
				{sectionBusyKey}
				pointingKey={pointingSectionKey}
				toggleDisabled={homing || !!movingTo || hasAnyClearing() || sectionBusyKey !== null}
				pointDisabled={homing || !!movingTo || pointingSectionKey !== null}
				onToggleColumn={(sectionIndex, enabled) =>
					void setSectionEnabled('column', enabled, { section_index: sectionIndex }, `col-${sectionIndex}`)}
				onPointSection={(sectionIndex) => void pointAtSection(sectionIndex)}
			/>
		{/if}

		<StatusBanner message={statusMsg} variant="success" />
		<StatusBanner message={error ?? ''} variant="error" />

		{#if !loading && layers.length > 0}
			<BinSearchBar bind:query={searchQuery} matchCount={searchMatchCount} totalBins={totalBinCount} />
		{/if}

		{#if loading}
			<div class="flex flex-col gap-6">
				{#each Array(2) as _layerUnused}
					<div class="border border-border">
						<div class="flex items-center justify-between border-b border-border bg-surface px-4 py-3">
							<Skeleton class="h-6 w-40" />
							<Skeleton class="h-9 w-72" />
						</div>
						<div class="grid grid-cols-6 gap-3 p-3">
							{#each Array(6) as _binUnused}
								<div class="flex flex-col border border-border">
									<div class="border-b border-border bg-surface px-3 py-2">
										<Skeleton class="h-5 w-3/4" />
									</div>
									<div class="grid grid-cols-4 gap-2 p-3">
										{#each Array(4) as _thumbUnused}
											<Skeleton class="aspect-square w-full" />
										{/each}
									</div>
									<div class="flex items-center justify-between border-t border-border px-3 py-2">
										<Skeleton class="h-4 w-16" />
										<Skeleton class="h-4 w-12" />
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		{:else if layers.length === 0}
			<p class="text-text-muted">No storage layers configured.</p>
		{:else}
			<div class="flex flex-col gap-6">
				{#each layers as layer (layer.layer_index)}
					{@const layerBusy = isLayerClearing(layer.layer_index)}
					{@const layerIsActive = activeLayer === layer.layer_index}
					<LayerPanel
						{layer}
						isActive={layerIsActive}
						{layerBusy}
						layerClearingLabel={layerClearingLabel(layer.layer_index)}
						emptyBusy={hasClearingKey(`empty-layer-${layer.layer_index}`)}
						resetBusy={hasClearingKey(`reset-layer-${layer.layer_index}`)}
						niiBusy={niiBusyLayer === layer.layer_index}
						niiDisabled={niiBusyLayer !== null}
						controlsDisabled={homing || !!movingTo || hasAnyClearing() || togglingLayerKey !== null}
						clearDisabled={homing || !!movingTo || isGlobalClearing() || layerBusy || togglingLayerKey !== null}
						sectionToggleDisabled={homing || !!movingTo || hasAnyClearing() || sectionBusyKey !== null}
						pointDisabled={homing || !!movingTo || pointingSectionKey !== null}
						pointingKey={pointingSectionKey}
						{contentsLoaded}
						contentsFor={(bin) => contentsForBin(layer.layer_index, bin)}
						setMetaFor={(bin) => assignedSetMeta(bin.category_ids)}
						setProgressFor={(bin) => binSetProgress(bin.category_ids)}
						isCurrentBin={(bin) => isCurrentBin(bin) && layerIsActive}
						isMovingBin={(bin) => movingTo === `${layer.layer_index}-${bin.section_index}-${bin.bin_index}`}
						isClearingBin={(bin) => isBinClearing(layer.layer_index, bin.section_index, bin.bin_index)}
						binClearingLabel={(bin) => binClearingLabel(layer.layer_index, bin.section_index, bin.bin_index)}
						sectionEnabled={(sectionIndex) => sectionEnabled(layer, sectionIndex)}
						moveDisabled={!!movingTo || homing || hasAnyClearing()}
						{searchActive}
						searchMatch={(bin) => binMatchesSearch(layer.layer_index, bin)}
						onToggleEnabled={(enabled) => void toggleLayerEnabled(layer.layer_index, enabled)}
						onEmptyLayer={() =>
							void runBinAction(
								'contents/clear',
								'layer',
								{ layer_index: layer.layer_index },
								`Please make sure layer ${layer.layer_index + 1} is physically empty first. This will mark all bins on that layer as emptied, but keep their assignments.`,
								`empty-layer-${layer.layer_index}`
							)}
						onResetLayer={() =>
							void runBinReset(
								'layer',
								layer.layer_index,
								`Please make sure layer ${layer.layer_index + 1} is physically empty first. This will remove all learned assignments from that layer and mark its bins as empty.`,
								`reset-layer-${layer.layer_index}`
							)}
						onToggleNii={(enabled) => void setLayerNotInInventory(layer.layer_index, enabled)}
						onToggleSection={(sectionIndex, enabled) =>
							void setSectionEnabled(
								'section',
								enabled,
								{ layer_index: layer.layer_index, section_index: sectionIndex },
								`sec-${layer.layer_index}-${sectionIndex}`
							)}
						onPointSection={(sectionIndex) => void pointAtSection(sectionIndex)}
						onOpenDetails={(bin) => openBinDetails(layer.layer_index, bin)}
						onMoveTo={(bin) => void moveToBin(layer.layer_index, bin.section_index, bin.bin_index)}
						onEmptyBin={(bin) =>
							void runBinAction(
								'contents/clear',
								'bin',
								{ layer_index: layer.layer_index, section_index: bin.section_index, bin_index: bin.bin_index },
								`Please make sure bin ${bin.global_index + 1} is physically empty first. This will mark the bin as emptied but keep its assignment.`,
								`empty-bin-${layer.layer_index}-${bin.section_index}-${bin.bin_index}`
							)}
						onResetBin={(bin) =>
							void runBinAction(
								'categories/clear',
								'bin',
								{ layer_index: layer.layer_index, section_index: bin.section_index, bin_index: bin.bin_index },
								`Please make sure bin ${bin.global_index + 1} is physically empty first. This will remove the learned assignment for just this bin and mark it as empty.`,
								`reset-bin-${layer.layer_index}-${bin.section_index}-${bin.bin_index}`
							)}
					/>
				{/each}

				<DiscardBinCard />
			</div>
		{/if}
	</div>

	<SnapshotsModal bind:open={snapshotsOpen} baseUrl={baseUrl()} />

	<BinDetailsModal
		bind:open={detailsOpen}
		{detailsBin}
		baseUrl={baseUrl()}
		{layers}
		onSaved={(message) => {
			statusMsg = message;
			void loadLayout();
		}}
		onError={(message) => (error = message)}
	/>
</div>

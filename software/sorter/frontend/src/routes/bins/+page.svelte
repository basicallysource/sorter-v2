<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { components } from '$lib/api/rest';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import BinLayoutSection from '$lib/components/bins/BinLayoutSection.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { Button, SelectMenu } from '$lib/components/primitives';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';
	import { ArchiveX, Crosshair, FolderOutput, Home, Loader2, Plus, Tag, X } from 'lucide-svelte';

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
	type BricklinkPartResponse = components['schemas']['BricklinkPartResponse'];
	let activeBaseUrl = $state(baseUrl());

	type BinInfo = {
		section_index: number;
		bin_index: number;
		global_index: number;
		size: string;
		angle: number;
		category_ids: string[];
		not_in_inventory?: boolean;
	};

	type LayerInfo = {
		layer_index: number;
		enabled: boolean;
		section_count: number;
		section_enabled?: boolean[];
		bin_count: number;
		max_pieces_per_bin: number | null;
		bins: BinInfo[];
	};

	type BinContentItem = {
		key: string;
		part_id?: string | null;
		color_id?: string | null;
		color_name?: string | null;
		category_id?: string | null;
		classification_status?: string | null;
		count: number;
		last_distributed_at?: number | null;
		thumbnail?: string | null;
		top_image?: string | null;
		bottom_image?: string | null;
		brickognize_preview_url?: string | null;
	};

	type BinContents = {
		bin_key: string;
		layer_index: number;
		section_index: number;
		bin_index: number;
		piece_count: number;
		unique_item_count: number;
		last_distributed_at?: number | null;
		items: BinContentItem[];
		recent_pieces: BinContentItem[];
	};

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
	let detailsBin = $state<{
		bin: BinInfo;
		layerIndex: number;
		contents: BinContents | null;
	} | null>(null);
	let bricklinkCache = $state<Map<string, BricklinkPartResponse | null>>(new Map());

	// Manual category assignment editor (lives inside the bin details modal).
	// assignSelected is the working set the operator is editing; it's seeded from
	// the bin's saved category_ids when the modal opens and only changes on
	// explicit user action, so the 2s layout refresh never clobbers an edit.
	let assignSelected = $state<string[]>([]);
	let assignSearch = $state('');
	let savingAssign = $state(false);
	let assignDropdownOpen = $state(false);

	type SetProgressSummary = { total_needed: number; total_found: number; pct: number };
	let setProgressByCategoryId = $state<Record<string, SetProgressSummary>>({});

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

	let niiBusyLayer = $state<number | null>(null);
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

	function setProgressFor(categoryIds: string[]): SetProgressSummary | null {
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
		// fetchBricklinkData is cached per part, so re-applying the full snapshot
		// only hits the (slow) BrickLink API for parts we haven't seen yet.
		for (const bin of Object.values(next)) {
			for (const item of bin.items) {
				if (item.part_id) void fetchBricklinkData(item.part_id);
			}
		}
	}

	async function loadBinContents() {
		try {
			const res = await fetch(`${baseUrl()}/api/bins/contents`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			applyBinsContents(data.bins);
		} catch {
			// Keep last known contents on transient failures.
		}
	}

	async function fetchBricklinkData(partId: string) {
		if (bricklinkCache.has(partId)) return;
		bricklinkCache = new Map(bricklinkCache).set(partId, null);
		try {
			const res = await fetch(`${baseUrl()}/bricklink/part/${encodeURIComponent(partId)}`);
			if (res.ok) {
				const data: BricklinkPartResponse = await res.json();
				bricklinkCache = new Map(bricklinkCache).set(partId, data);
			}
		} catch {
			// ignore lookup errors
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

	function formatCategoryName(categoryId: string | null | undefined): string {
		if (!categoryId) return '';
		const mapped = sortingProfileStore.getCategoryName(categoryId);
		const value = mapped ?? categoryId;
		if (value.toLowerCase() === 'misc') return 'Misc';
		return value;
	}

	function categoryLabel(categoryIds: string[]): string {
		if (!categoryIds || categoryIds.length === 0) return '';
		return categoryIds.map((id) => formatCategoryName(id)).join(', ');
	}

	function binsForSection(layer: LayerInfo, sectionIndex: number): BinInfo[] {
		return layer.bins.filter((b) => b.section_index === sectionIndex);
	}

	function formatLastSeen(timestamp: number | null | undefined): string {
		if (!timestamp) return 'n/a';
		return new Date(timestamp * 1000).toLocaleString();
	}

	function previewUrl(item: BinContentItem | null): string | null {
		if (!item) return null;
		if (item.part_id) {
			const partInfo = bricklinkCache.get(item.part_id);
			if (partInfo?.image_url) return partInfo.image_url;
			if (partInfo?.thumbnail_url) return partInfo.thumbnail_url;
		}
		if (item.brickognize_preview_url) return item.brickognize_preview_url;
		if (item.thumbnail) return `data:image/jpeg;base64,${item.thumbnail}`;
		if (item.top_image) return `data:image/jpeg;base64,${item.top_image}`;
		if (item.bottom_image) return `data:image/jpeg;base64,${item.bottom_image}`;
		return null;
	}

	function pieceTooltip(item: BinContentItem): string {
		const label = item.part_id
			? `${item.part_id}${item.color_name ? ` · ${item.color_name}` : ''}`
			: 'Unknown part';
		const status = item.classification_status ? ` (${item.classification_status})` : '';
		return `${label}${status}`;
	}

	function itemDisplayName(item: BinContentItem): string {
		const partInfo = item.part_id ? bricklinkCache.get(item.part_id) : null;
		return partInfo?.name || item.part_id || 'Unknown part';
	}

	function itemSecondaryText(item: BinContentItem): string {
		const bits = [item.part_id, item.color_name].filter((value): value is string => Boolean(value));
		return bits.join(' · ') || 'Unrecognized item';
	}

	function assignedSetMeta(
		categoryIds: string[]
	): { name: string; set_num?: string; img_url?: string } | null {
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

	function cardPreviewItems(contents: BinContents | null): BinContentItem[] {
		if (!contents) return [];
		if (Array.isArray(contents.recent_pieces) && contents.recent_pieces.length > 0) {
			return contents.recent_pieces.slice(0, 8);
		}
		return [...contents.items]
			.sort((a, b) => Number(b.last_distributed_at ?? 0) - Number(a.last_distributed_at ?? 0))
			.slice(0, 8);
	}

	function openBinDetails(layerIndex: number, bin: BinInfo) {
		const contents = contentsForBin(layerIndex, bin);
		detailsBin = { layerIndex, bin, contents };
		detailsOpen = true;
		assignSelected = [...bin.category_ids];
		assignSearch = '';
		assignDropdownOpen = false;
		for (const item of contents?.items ?? []) {
			if (item.part_id) void fetchBricklinkData(item.part_id);
		}
	}

	function availableCategories(): { id: string; name: string }[] {
		const cats = sortingProfileStore.data?.categories ?? {};
		return Object.entries(cats)
			.map(([id, cat]) => ({ id, name: cat?.name ?? id }))
			.sort((a, b) => a.name.localeCompare(b.name));
	}

	// Where each category is currently assigned across the persisted layout, so
	// the picker can flag categories already living in another bin (assigning
	// here will move them). Keyed by category_id → that bin's global index.
	function categoryLocations(): Record<string, { layerIndex: number; globalIndex: number }> {
		const map: Record<string, { layerIndex: number; globalIndex: number }> = {};
		for (const layer of layers) {
			for (const bin of layer.bins) {
				for (const id of bin.category_ids) {
					if (!(id in map)) {
						map[id] = { layerIndex: layer.layer_index, globalIndex: bin.global_index };
					}
				}
			}
		}
		return map;
	}

	function assignedElsewhereLabel(id: string): string | null {
		const loc = categoryLocations()[id];
		if (!loc) return null;
		if (detailsBin && loc.globalIndex === detailsBin.bin.global_index) return null;
		return `Bin ${loc.globalIndex + 1}`;
	}

	// Dropdown candidates: every profile category not already in the working set,
	// filtered by the search box.
	function pickableCategories(): { id: string; name: string }[] {
		const query = assignSearch.trim().toLowerCase();
		return availableCategories().filter((cat) => {
			if (assignSelected.includes(cat.id)) return false;
			if (!query) return true;
			return cat.name.toLowerCase().includes(query) || cat.id.toLowerCase().includes(query);
		});
	}

	function addAssignCategory(id: string) {
		if (!assignSelected.includes(id)) assignSelected = [...assignSelected, id];
		assignSearch = '';
		assignDropdownOpen = false;
	}

	function removeAssignCategory(id: string) {
		assignSelected = assignSelected.filter((c) => c !== id);
	}

	function assignDirty(): boolean {
		if (!detailsBin) return false;
		const current = [...detailsBin.bin.category_ids].sort();
		const next = [...assignSelected].sort();
		return current.length !== next.length || current.some((c, i) => c !== next[i]);
	}

	async function saveAssignment() {
		if (!detailsBin || savingAssign) return;
		savingAssign = true;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/categories/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					layer_index: detailsBin.layerIndex,
					section_index: detailsBin.bin.section_index,
					bin_index: detailsBin.bin.bin_index,
					category_ids: assignSelected
				})
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			assignSelected = Array.isArray(data.category_ids) ? data.category_ids : assignSelected;
			assignDropdownOpen = false;
			statusMsg = data?.message ?? 'Bin categories updated.';
			await loadLayout();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to assign categories';
		} finally {
			savingAssign = false;
		}
	}

	function openSetChecklist(categoryIds: string[]) {
		if (!categoryIds || categoryIds.length !== 1) return;
		const categoryId = categoryIds[0];
		const target = `${window.location.origin}/bins/set-view/${encodeURIComponent(categoryId)}?base=${encodeURIComponent(baseUrl())}`;
		window.open(target, '_blank', 'noopener,noreferrer');
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
			clearingStates.find((entry) => entry.scope === 'layer' && entry.layerIndex === layerIndex) ??
			null;
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
		const interval = setInterval(() => {
			void loadLayout();
			void loadBinContents();
			void loadSetProgress();
		}, 2000);
		return () => clearInterval(interval);
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
		setProgressByCategoryId = {};
		detailsOpen = false;
		detailsBin = null;
		movingTo = null;
		homing = false;
		clearingStates = [];
		togglingLayerKey = null;
		void loadLayout();
		void loadBinContents();
		void loadSetProgress();
		void loadBinSettings();
		void sortingProfileStore.load(nextBaseUrl).catch(() => {});
	});

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

<div class="min-h-screen bg-bg">
	<AppHeader />
	{#if isGlobalClearing()}
		<div class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4">
			<div class="w-full max-w-md border border-[#E2E0DB] bg-white p-6 shadow-xl">
				<div class="flex items-start gap-4">
					<div
						class="flex h-10 w-10 items-center justify-center border border-[#E2E0DB] bg-surface"
					>
						<Loader2 size={18} class="animate-spin text-primary" />
					</div>
					<div class="space-y-2">
						<h3 class="text-lg font-semibold text-[#1A1A1A]">{globalClearingTitle()}</h3>
						<p class="text-sm leading-6 text-[#66635C]">{globalClearingDescription()}</p>
						<p class="text-xs tracking-wide text-[#8B887F] uppercase">
							Please wait while the sorter refreshes the bin state.
						</p>
					</div>
				</div>
			</div>
		</div>
	{/if}
	<div class="p-4 sm:p-6">
		<div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
			<div>
				<h2 class="text-xl font-bold whitespace-nowrap text-text">Bin Grid</h2>
			</div>
			<div class="flex flex-wrap items-center gap-3">
				<button
					onclick={homeChute}
					disabled={homing || !!movingTo || hasAnyClearing() || togglingLayerKey !== null}
					class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50 {homing
						? 'animate-pulse'
						: ''}"
					title="Home chute (find endstop)"
				>
					<Home size={16} />
					{homing ? 'Homing...' : 'Home Chute'}
				</button>
				<button
					onclick={() =>
						void runBinAction(
							'contents/clear',
							'all',
							{},
							'Please make sure all physical bins are empty first. This will mark every bin on the machine as emptied, but keep the current profile-to-bin assignments in place.',
							'empty-all'
						)}
					disabled={homing || !!movingTo || hasAnyClearing() || togglingLayerKey !== null}
					class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
					title="Empty all bins but keep assignments"
				>
					<FolderOutput size={16} />
					{hasClearingKey('empty-all') ? 'Emptying…' : 'Empty All Bins'}
				</button>
				<button
					onclick={() =>
						void runBinReset(
							'all',
							undefined,
							'Please make sure all physical bins are empty first. This will remove every learned bin assignment on the machine and mark all bins as empty.',
							'reset-all'
						)}
					disabled={homing || !!movingTo || hasAnyClearing() || togglingLayerKey !== null}
					class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
					title="Reset all bins and remove assignments"
				>
					<ArchiveX size={16} />
					{hasClearingKey('reset-all') ? 'Resetting…' : 'Reset All Bins'}
				</button>
			</div>
		</div>

		<BinLayoutSection baseUrl={baseUrl()} profileId={activeProfileId} profileName={activeProfileName} />

		<div
			class="mb-4 flex items-center justify-between gap-4 border border-[#E2E0DB] bg-surface px-4 py-3"
		>
			<div class="pr-4">
				<div class="text-sm font-medium text-[#1A1A1A]">Allow multiple categories per bin</div>
				<div class="mt-0.5 text-sm text-[#66635C]">
					When every bin already has an assignment, keep sorting new categories by combining them
					into existing bins (least-loaded first) instead of sending them to the discard
					passthrough.
				</div>
			</div>
			<label class="flex items-center">
				<button
					type="button"
					role="switch"
					aria-checked={allowMultiCategory}
					aria-label="Allow multiple categories per bin"
					onclick={() => void toggleMultiCategory()}
					disabled={savingMultiCategory}
					class={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${allowMultiCategory ? 'bg-success' : 'bg-[#C9C6BF]'} disabled:cursor-not-allowed disabled:opacity-50`}
				>
					<span
						class={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${allowMultiCategory ? 'translate-x-6' : 'translate-x-1'}`}
					></span>
				</button>
			</label>
		</div>

		<div class="mb-4 border border-[#E2E0DB] bg-surface px-4 py-3">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="pr-4">
					<div class="text-sm font-medium text-[#1A1A1A]">Auto-assign bins</div>
					<div class="mt-0.5 text-sm text-[#66635C]">
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
						class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3.5 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
					>
						{autoAssignBusy ? 'Assigning…' : 'Auto-assign'}
					</button>
					<button
						type="button"
						onclick={() => void runAutoAssign(true)}
						disabled={autoAssignBusy}
						title="Pack every ranked category in, sharing bins once they run out"
						class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3.5 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
					>
						{autoAssignBusy ? 'Assigning…' : 'Auto-assign + overlap'}
					</button>
				</div>
			</div>
			{#if autoAssignResult}
				<div class="mt-2 text-sm text-[#66635C]">{autoAssignResult}</div>
			{/if}
		</div>

		{#if !loading && layers.length > 0 && maxSectionCount() > 0}
			<div class="mb-4 border border-[#E2E0DB] bg-surface px-4 py-3">
				<div class="mb-2 flex items-center justify-between gap-4">
					<div>
						<div class="text-sm font-medium text-[#1A1A1A]">Columns (sections across all layers)</div>
						<div class="mt-0.5 text-sm text-[#66635C]">
							Disable a whole column to stop sorting into that section on every layer, or
							point the chute at it to find it.
						</div>
					</div>
				</div>
				<div class="flex flex-wrap gap-2">
					{#each Array(maxSectionCount()) as _, sectionIndex}
						{@const colOn = columnEnabled(sectionIndex)}
						{@const colBusy = sectionBusyKey === `col-${sectionIndex}`}
						<div class="flex items-center gap-2 border border-[#E2E0DB] {colOn ? 'bg-white' : 'bg-[#F2F0EB]'} px-3 py-1.5">
							<span class="text-sm font-semibold {colOn ? 'text-[#1A1A1A]' : 'text-[#9A968E]'}">
								Col {sectionIndex + 1}
							</span>
							<button
								type="button"
								role="switch"
								aria-checked={colOn}
								aria-label={colOn ? `Disable column ${sectionIndex + 1}` : `Enable column ${sectionIndex + 1}`}
								onclick={() =>
									void setSectionEnabled('column', !colOn, { section_index: sectionIndex }, `col-${sectionIndex}`)}
								disabled={homing || !!movingTo || hasAnyClearing() || sectionBusyKey !== null}
								class={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${colOn ? 'bg-success' : 'bg-[#C9C6BF]'} disabled:cursor-not-allowed disabled:opacity-50`}
							>
								<span class={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${colOn ? 'translate-x-5' : 'translate-x-1'}`}></span>
							</button>
							<button
								type="button"
								onclick={() => void pointAtSection(sectionIndex)}
								disabled={homing || !!movingTo || pointingSectionKey !== null}
								class="flex items-center justify-center border border-[#E2E0DB] bg-white p-1 text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
								title="Point chute at section {sectionIndex + 1}"
							>
								{#if pointingSectionKey === `point-${sectionIndex}`}
									<Loader2 size={14} class="animate-spin" />
								{:else}
									<Crosshair size={14} />
								{/if}
							</button>
							{#if colBusy}
								<Loader2 size={14} class="animate-spin text-primary" />
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<StatusBanner message={statusMsg} variant="success" />
		<StatusBanner message={error ?? ''} variant="error" />

		{#if loading}
			<p class="text-[#7A7770]">Loading bin layout...</p>
		{:else if layers.length === 0}
			<p class="text-[#7A7770]">No storage layers configured.</p>
		{:else}
			<div class="flex flex-col gap-6">
				{#each layers as layer}
					{@const isActive = activeLayer === layer.layer_index}
					{@const layerBusy = isLayerClearing(layer.layer_index)}
					{@const layerNii = layer.bins.length > 0 && layer.bins.every((b) => b.not_in_inventory)}
					<div class="relative border border-[#E2E0DB] {!layer.enabled ? 'opacity-60' : ''}">
						{#if layerBusy}
							<div
								class="absolute inset-0 z-20 flex items-center justify-center bg-white/78 backdrop-blur-[1px]"
							>
								<div
									class="flex items-center gap-3 border border-[#E2E0DB] bg-white px-4 py-3 shadow-sm"
								>
									<Loader2 size={16} class="animate-spin text-primary" />
									<div class="text-sm font-medium text-[#1A1A1A]">
										{layerClearingLabel(layer.layer_index)}
									</div>
								</div>
							</div>
						{/if}
						<div
							class="flex items-center justify-between border-b border-[#E2E0DB] bg-surface px-4 py-3"
						>
							<div class="flex items-center gap-3">
								<h3 class="text-base font-semibold text-[#1A1A1A]">
									Layer {layer.layer_index + 1}
									<span class="ml-2 text-sm font-normal text-[#7A7770]">{layer.bin_count} bins</span
									>
								</h3>
							</div>
							<div class="flex items-center gap-3">
								{#if isActive}
									<span
										class="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-success uppercase"
									>
										<span class="inline-block h-2 w-2 bg-success"></span>
										Active
									</span>
								{/if}
								<label class="flex items-center">
									<button
										type="button"
										role="switch"
										aria-checked={layer.enabled}
										aria-label={layer.enabled
											? `Disable layer ${layer.layer_index + 1}`
											: `Enable layer ${layer.layer_index + 1}`}
										onclick={() => void toggleLayerEnabled(layer.layer_index, !layer.enabled)}
										disabled={homing || !!movingTo || hasAnyClearing() || togglingLayerKey !== null}
										class={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${layer.enabled ? 'bg-success' : 'bg-[#C9C6BF]'} disabled:cursor-not-allowed disabled:opacity-50`}
									>
										<span
											class={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${layer.enabled ? 'translate-x-6' : 'translate-x-1'}`}
										></span>
									</button>
								</label>
								<button
									type="button"
									onclick={() =>
										void runBinAction(
											'contents/clear',
											'layer',
											{ layer_index: layer.layer_index },
											`Please make sure layer ${layer.layer_index + 1} is physically empty first. This will mark all bins on that layer as emptied, but keep their assignments.`,
											`empty-layer-${layer.layer_index}`
										)}
									disabled={homing ||
										!!movingTo ||
										isGlobalClearing() ||
										layerBusy ||
										togglingLayerKey !== null}
									class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3.5 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
								>
									<FolderOutput size={14} />
									{hasClearingKey(`empty-layer-${layer.layer_index}`) ? 'Emptying…' : 'Empty Layer'}
								</button>
								<button
									type="button"
									onclick={() =>
										void runBinReset(
											'layer',
											layer.layer_index,
											`Please make sure layer ${layer.layer_index + 1} is physically empty first. This will remove all learned assignments from that layer and mark its bins as empty.`,
											`reset-layer-${layer.layer_index}`
										)}
									disabled={homing ||
										!!movingTo ||
										isGlobalClearing() ||
										layerBusy ||
										togglingLayerKey !== null}
									class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3.5 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
								>
									<ArchiveX size={14} />
									{hasClearingKey(`reset-layer-${layer.layer_index}`)
										? 'Resetting…'
										: 'Reset Layer'}
								</button>
								<button
									type="button"
									onclick={() => void setLayerNotInInventory(layer.layer_index, !layerNii)}
									disabled={niiBusyLayer !== null}
									title="Route pieces not in the active BrickLink inventory (.bsx) into this layer's bins"
									class="flex items-center gap-2 border px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 {layerNii
										? 'border-warning bg-warning/[0.12] text-warning'
										: 'border-[#E2E0DB] bg-white text-[#1A1A1A] hover:bg-[#F7F6F3]'}"
								>
									{niiBusyLayer === layer.layer_index
										? 'Saving…'
										: layerNii
											? 'Not-in-inventory: ON'
											: 'Not-in-inventory mode'}
								</button>
							</div>
						</div>
						<div class="flex flex-wrap items-center gap-2 border-b border-[#E2E0DB] bg-[#FAFAF8] px-3 py-2">
							<span class="text-xs font-semibold uppercase tracking-wide text-[#7A7770]">Sections</span>
							{#each Array(layer.section_count) as _, sectionIndex}
								{@const secOn = sectionEnabled(layer, sectionIndex)}
								{@const secKey = `sec-${layer.layer_index}-${sectionIndex}`}
								<div class="flex items-center gap-1.5 border border-[#E2E0DB] {secOn ? 'bg-white' : 'bg-[#F2F0EB]'} px-2 py-1">
									<span class="text-sm {secOn ? 'text-[#1A1A1A]' : 'text-[#9A968E]'}">S{sectionIndex + 1}</span>
									<button
										type="button"
										role="switch"
										aria-checked={secOn}
										aria-label={secOn ? `Disable layer ${layer.layer_index + 1} section ${sectionIndex + 1}` : `Enable layer ${layer.layer_index + 1} section ${sectionIndex + 1}`}
										onclick={() =>
											void setSectionEnabled('section', !secOn, { layer_index: layer.layer_index, section_index: sectionIndex }, secKey)}
										disabled={homing || !!movingTo || hasAnyClearing() || sectionBusyKey !== null}
										class={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${secOn ? 'bg-success' : 'bg-[#C9C6BF]'} disabled:cursor-not-allowed disabled:opacity-50`}
									>
										<span class={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${secOn ? 'translate-x-5' : 'translate-x-1'}`}></span>
									</button>
									<button
										type="button"
										onclick={() => void pointAtSection(sectionIndex)}
										disabled={homing || !!movingTo || pointingSectionKey !== null}
										class="flex items-center justify-center border border-[#E2E0DB] bg-white p-1 text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
										title="Point chute at section {sectionIndex + 1}"
									>
										{#if pointingSectionKey === `point-${sectionIndex}`}
											<Loader2 size={13} class="animate-spin" />
										{:else}
											<Crosshair size={13} />
										{/if}
									</button>
								</div>
							{/each}
						</div>
						<div
							class="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
						>
							{#each layer.bins as bin}
								{@const key = `${layer.layer_index}-${bin.section_index}-${bin.bin_index}`}
								{@const isCurrent = isCurrentBin(bin) && isActive}
								{@const isMoving = movingTo === key}
								{@const isClearing = isBinClearing(
									layer.layer_index,
									bin.section_index,
									bin.bin_index
								)}
								{@const catLabel = categoryLabel(bin.category_ids)}
								{@const contents = contentsForBin(layer.layer_index, bin)}
								{@const previewItems = cardPreviewItems(contents)}
								{@const setMeta = assignedSetMeta(bin.category_ids)}
								{@const setProgress = setProgressFor(bin.category_ids)}
								{@const secOn = sectionEnabled(layer, bin.section_index)}
								<div class="group relative flex h-full flex-col border border-[#E2E0DB] bg-white {secOn ? '' : 'opacity-50'}">
									{#if !secOn}
										<div class="absolute right-1 top-1 z-10 bg-[#9A968E] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-white">
											Section off
										</div>
									{/if}
									{#if isClearing}
										<div
											class="absolute inset-0 z-20 flex items-center justify-center bg-white/82 backdrop-blur-[1px]"
										>
											<div
												class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3 py-2 shadow-sm"
											>
												<Loader2 size={14} class="animate-spin text-primary" />
												<span class="text-xs font-semibold tracking-wide text-[#1A1A1A] uppercase">
													{binClearingLabel(layer.layer_index, bin.section_index, bin.bin_index)}
												</span>
											</div>
										</div>
									{/if}
									<div
										class="flex items-center justify-between border-b border-[#E2E0DB] bg-surface px-3 py-2"
									>
										<div
											class="pr-3 text-base font-semibold {isCurrent
												? 'text-success'
												: 'text-[#1A1A1A]'}"
										>
											{#if catLabel}
												{bin.global_index + 1}: {catLabel}
											{:else}
												Bin {bin.global_index + 1}
											{/if}
										</div>
										<div class="flex items-center gap-1.5">
											<button
												type="button"
												onclick={() => openBinDetails(layer.layer_index, bin)}
												class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A]"
												title="Assign categories to this bin"
											>
												<Tag size={13} />
											</button>
											<button
												type="button"
												onclick={() =>
													moveToBin(layer.layer_index, bin.section_index, bin.bin_index)}
												disabled={!!movingTo || homing || hasAnyClearing() || !layer.enabled}
												class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
												title="Move chute to this bin"
											>
												<Crosshair size={13} />
											</button>
											{#if contents && contents.piece_count > 0}
												<button
													type="button"
													onclick={() =>
														void runBinAction(
															'contents/clear',
															'bin',
															{
																layer_index: layer.layer_index,
																section_index: bin.section_index,
																bin_index: bin.bin_index
															},
															`Please make sure bin ${bin.global_index + 1} is physically empty first. This will mark the bin as emptied but keep its assignment.`,
															`empty-bin-${key}`
														)}
													disabled={!!movingTo ||
														homing ||
														isGlobalClearing() ||
														layerBusy ||
														isClearing}
													class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
													title="Empty this bin but keep assignment"
												>
													<FolderOutput size={13} />
												</button>
											{/if}
											{#if bin.category_ids.length > 0}
												<button
													type="button"
													onclick={() =>
														void runBinAction(
															'categories/clear',
															'bin',
															{
																layer_index: layer.layer_index,
																section_index: bin.section_index,
																bin_index: bin.bin_index
															},
															`Please make sure bin ${bin.global_index + 1} is physically empty first. This will remove the learned assignment for just this bin and mark it as empty.`,
															`reset-bin-${key}`
														)}
													disabled={!!movingTo ||
														homing ||
														isGlobalClearing() ||
														layerBusy ||
														isClearing}
													class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
													title="Reset this bin and clear assignment"
												>
													<ArchiveX size={13} />
												</button>
											{/if}
										</div>
									</div>
									{#if layer.max_pieces_per_bin && layer.max_pieces_per_bin > 0}
										{@const fillCount = contents?.piece_count ?? 0}
										{@const fillMax = layer.max_pieces_per_bin}
										{@const fillPct = Math.min(100, Math.max(0, (fillCount / fillMax) * 100))}
										{@const isFull = fillCount >= fillMax}
										{@const isNearFull = fillCount / fillMax >= 0.85 && !isFull}
										<div
											class="relative h-4 w-full overflow-hidden border-b border-[#E2E0DB] bg-[#F0EFEB]"
											title="{fillCount} / {fillMax} pieces"
										>
											<div
												class="absolute inset-y-0 left-0 transition-all {isFull
													? 'bg-danger'
													: isNearFull
														? 'bg-warning'
														: 'bg-success'}"
												style="width: {fillPct}%"
											></div>
											<div
												class="relative flex h-full items-center justify-center text-xs font-semibold text-[#1A1A1A] tabular-nums mix-blend-luminosity"
											>
												{fillCount} / {fillMax}
											</div>
										</div>
									{/if}
									<button
										onclick={() => openBinDetails(layer.layer_index, bin)}
										class="relative flex min-h-[6.25rem] w-full flex-1 flex-col items-start justify-start px-3 py-3 text-left transition-colors {isCurrent
											? 'bg-success/8 ring-2 ring-success ring-inset'
											: layer.enabled
												? 'hover:bg-[#F7F6F3]'
												: 'cursor-not-allowed'} {isMoving || isClearing ? 'animate-pulse' : ''}"
										title={`Bin ${bin.global_index + 1}${catLabel ? ` — ${catLabel}` : ''}`}
									>
										{#if contents}
											<div class="mt-1 flex w-full flex-col gap-3">
												{#if setMeta}
													<div class="relative w-full border border-[#E2E0DB] bg-bg">
														{#if setMeta.img_url}
															<img
																src={setMeta.img_url}
																alt={setMeta.name}
																class="block max-h-[400px] w-full bg-white object-contain"
															/>
														{/if}
														{#if setMeta.set_num}
															<div
																class="absolute top-2 right-2 border border-border bg-white/95 px-2 py-1 text-xs font-medium text-[#1A1A1A] shadow-sm"
															>
																{setMeta.set_num}
															</div>
														{/if}
													</div>
												{/if}
												<div class="grid w-full grid-cols-4 gap-2">
													{#each previewItems as piece}
														{@const thumb = previewUrl(piece)}
														<div
															class="flex aspect-square w-full items-center justify-center"
															title={pieceTooltip(piece)}
														>
															{#if thumb}
																<img
																	src={thumb}
																	alt={pieceTooltip(piece)}
																	class="h-full w-full object-contain"
																/>
															{/if}
														</div>
													{/each}
												</div>
											</div>
										{/if}
									</button>
									{#if !catLabel && !contents}
										<div
											class="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center opacity-0 transition-opacity group-hover:opacity-100"
										>
											<div class="text-sm text-text-muted">
												No category assigned yet. No recorded pieces yet.
											</div>
										</div>
									{/if}
									{#if setProgress && setProgress.total_needed > 0}
										{@const clampedPct = Math.min(100, Math.max(0, setProgress.pct))}
										{@const isDone = setProgress.total_found >= setProgress.total_needed}
										<div
											class="relative h-5 w-full overflow-hidden border-t border-[#E2E0DB] bg-[#F0EFEB]"
											title="{setProgress.total_found} of {setProgress.total_needed} parts found"
										>
											<div
												class="absolute inset-y-0 left-0 transition-all {isDone
													? 'bg-success'
													: 'bg-primary'}"
												style="width: {clampedPct}%"
											></div>
											<div
												class="relative flex h-full items-center justify-center text-xs font-semibold text-[#1A1A1A] tabular-nums mix-blend-luminosity"
											>
												{setProgress.total_found} / {setProgress.total_needed} parts
											</div>
										</div>
									{/if}
									{#if contents}
										<div
											class="flex items-center justify-between border-t border-[#E2E0DB] px-3 py-2 text-xs text-[#66635C]"
										>
											<div>
												{contents.unique_item_count}
												{contents.unique_item_count === 1 ? 'type' : 'types'}
											</div>
											<div>{contents.piece_count} total</div>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/each}

				<!-- Virtual passthrough "bin" — pieces without a matching
				     rule fall through all layer doors to the discard
				     bucket below the machine. Represented so the operator
				     knows the output exists; not interactive, no real
				     physical slot. -->
				<div class="mt-4 flex flex-col border-2 border-dashed border-warning/50 bg-warning/[0.05]">
					<div
						class="flex items-center justify-between border-b border-warning/30 bg-warning/10 px-3 py-2"
					>
						<span class="text-sm font-semibold tracking-wider text-warning-dark uppercase">
							Discard Bin · Misc Passthrough
						</span>
						<span class="text-xs text-text-muted">virtual</span>
					</div>
					<div class="p-3 text-sm text-text-muted">
						Pieces that don't match any sorting rule (or whose category has no assigned bin) fall
						through all layer doors into the discard bucket below the machine. Empty it manually
						when it fills up.
					</div>
				</div>
			</div>
		{/if}
	</div>

	<Modal
		bind:open={detailsOpen}
		title={detailsBin ? `Bin ${detailsBin.bin.global_index + 1} Details` : 'Bin Details'}
		wide={true}
	>
		{#if detailsBin}
			{@const setMeta = assignedSetMeta(detailsBin.bin.category_ids)}
			<div class="space-y-4">
				<div
					class="grid gap-4 border border-border bg-surface px-4 py-4 text-sm text-text-muted md:grid-cols-3"
				>
					<div>
						<div class="text-xs tracking-wide uppercase">Layer</div>
						<div class="mt-1 text-base font-medium text-text">{detailsBin.layerIndex + 1}</div>
					</div>
					<div>
						<div class="text-xs tracking-wide uppercase">Assigned Category</div>
						<div class="mt-1 text-base font-medium text-text">
							{categoryLabel(detailsBin.bin.category_ids) || 'None'}
						</div>
					</div>
					<div>
						<div class="text-xs tracking-wide uppercase">Recorded Pieces</div>
						<div class="mt-1 text-base font-medium text-text">
							{detailsBin.contents?.piece_count ?? 0}
							{(detailsBin.contents?.piece_count ?? 0) === 1 ? 'piece' : 'pieces'}
						</div>
					</div>
				</div>

				<!-- Manual category assignment. Pick one or more sorting-profile
				     categories to route into this bin. Assigning a category here
				     removes it from any other bin (a category lives in one bin). -->
				<div class="border border-border bg-bg p-4">
					<div class="mb-2 flex items-center justify-between gap-3">
						<div class="flex items-center gap-2 text-sm font-semibold text-text">
							<Tag size={15} />
							Assign categories
						</div>
						<Button
							size="sm"
							variant="primary"
							loading={savingAssign}
							disabled={!assignDirty()}
							onclick={() => void saveAssignment()}
						>
							Save
						</Button>
					</div>
					<p class="mb-3 text-sm text-text-muted">
						Choose one or more categories from your sorting profile to route into this bin.
						Assigning a category here moves it out of whatever bin it was in before.
					</p>

					<div class="flex flex-wrap items-center gap-2">
						{#each assignSelected as id (id)}
							{@const elsewhere = assignedElsewhereLabel(id)}
							<span
								class="inline-flex items-center gap-1.5 border border-primary bg-primary/[0.08] px-2 py-1 text-sm text-text"
							>
								{formatCategoryName(id) || id}
								{#if elsewhere}
									<span class="text-xs text-text-muted">(was {elsewhere})</span>
								{/if}
								<button
									type="button"
									class="text-text-muted transition-colors hover:text-danger"
									onclick={() => removeAssignCategory(id)}
									aria-label={`Remove ${formatCategoryName(id) || id}`}
								>
									<X size={13} />
								</button>
							</span>
						{/each}

						<SelectMenu
							bind:open={assignDropdownOpen}
							bind:search={assignSearch}
							searchPlaceholder="Search categories…"
							width={320}
						>
							{#snippet trigger()}
								<span
									class="inline-flex items-center gap-1 border border-border bg-white px-2 py-1 text-sm text-text transition-colors hover:bg-surface"
								>
									<Plus size={14} />
									Add category
								</span>
							{/snippet}
							{#if availableCategories().length === 0}
								<div class="px-3 py-3 text-sm text-text-muted">
									No categories in the active sorting profile.
								</div>
							{:else}
								{#each pickableCategories() as cat (cat.id)}
									{@const elsewhere = assignedElsewhereLabel(cat.id)}
									<button
										type="button"
										onclick={() => addAssignCategory(cat.id)}
										class="flex w-full items-center justify-between gap-2 border-b border-border bg-white px-3 py-2 text-left text-sm transition-colors last:border-b-0 hover:bg-surface"
									>
										<span class="flex-1 text-text">{cat.name}</span>
										{#if elsewhere}
											<span
												class="shrink-0 border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted"
												title="Currently assigned here — adding will move it"
											>
												{elsewhere}
											</span>
										{/if}
									</button>
								{/each}
								{#if pickableCategories().length === 0}
									<div class="px-3 py-3 text-sm text-text-muted">
										{assignSearch.trim() ? `No categories match “${assignSearch}”.` : 'All categories are already added.'}
									</div>
								{/if}
							{/if}
						</SelectMenu>
					</div>

					{#if assignSelected.length === 0}
						<div class="mt-3 text-sm text-text-muted">
							No categories assigned — matching pieces fall through to the discard bin.
						</div>
					{/if}
				</div>

				{#if setMeta}
					<div class="border border-border bg-bg p-4">
						<div class="grid gap-4 md:grid-cols-[160px_1fr] md:items-center">
							<div class="flex items-center justify-center bg-surface p-3">
								{#if setMeta.img_url}
									<img
										src={setMeta.img_url}
										alt={setMeta.name}
										class="h-32 w-full object-contain"
									/>
								{/if}
							</div>
							<div>
								<div class="text-lg font-semibold text-text">{setMeta.name}</div>
								{#if setMeta.set_num}
									<div class="mt-1 text-sm text-text-muted">{setMeta.set_num}</div>
								{/if}
								<div class="mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
									<span class="border border-border bg-surface px-2 py-1"
										>{detailsBin.contents?.unique_item_count ?? 0}
										{(detailsBin.contents?.unique_item_count ?? 0) === 1
											? 'item type'
											: 'item types'}</span
									>
									<span class="border border-border bg-surface px-2 py-1"
										>{detailsBin.contents?.piece_count ?? 0} total pieces</span
									>
								</div>
								<div class="mt-4">
									<button
										type="button"
										onclick={() => openSetChecklist(detailsBin?.bin.category_ids ?? [])}
										class="border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg"
									>
										Open checklist
									</button>
								</div>
							</div>
						</div>
					</div>
				{/if}

				{#if !detailsBin.contents || detailsBin.contents.items.length === 0}
					<div class="border border-border bg-bg px-4 py-4 text-sm text-text-muted">
						No detailed piece records for this bin yet.
					</div>
				{:else}
					<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
						{#each detailsBin.contents.items as item}
							{@const hero = previewUrl(item)}
							<div class="overflow-hidden border border-border bg-bg">
								<div class="relative bg-surface p-4">
									{#if hero}
										<img src={hero} alt={pieceTooltip(item)} class="h-40 w-full object-contain" />
									{/if}
									<div
										class="absolute top-3 right-3 flex h-10 min-w-10 items-center justify-center bg-[#16A6B6] px-3 text-lg font-semibold text-white shadow-sm"
									>
										{item.count}
									</div>
								</div>
								<div class="px-4 py-3">
									<div class="text-base font-medium text-text">{itemDisplayName(item)}</div>
									<div class="mt-1 text-sm text-text-muted">{itemSecondaryText(item)}</div>
									<div class="mt-2 text-sm text-text-muted">
										{formatCategoryName(item.category_id) || 'No category'}
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</Modal>
</div>

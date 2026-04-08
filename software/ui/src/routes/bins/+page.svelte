<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { components } from '$lib/api/rest';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';
	import { Crosshair, Home, Trash2 } from 'lucide-svelte';

	const manager = getMachinesContext();
	type BricklinkPartResponse = components['schemas']['BricklinkPartResponse'];

	type BinInfo = {
		section_index: number;
		bin_index: number;
		global_index: number;
		size: string;
		angle: number;
		category_ids: string[];
	};

	type LayerInfo = {
		layer_index: number;
		enabled: boolean;
		section_count: number;
		bin_count: number;
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

	let layers = $state<LayerInfo[]>([]);
	let currentAngle = $state<number | null>(null);
	let activeLayer = $state<number | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let movingTo = $state<string | null>(null);
	let homing = $state(false);
	let statusMsg = $state('');
	let clearingKey = $state<string | null>(null);
	let togglingLayerKey = $state<number | null>(null);
	let contentsByKey = $state<Record<string, BinContents>>({});
	let detailsOpen = $state(false);
	let detailsBin = $state<{ bin: BinInfo; layerIndex: number; contents: BinContents | null } | null>(null);
	let bricklinkCache = $state<Map<string, BricklinkPartResponse | null>>(new Map());

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
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

	async function loadBinContents() {
		try {
			const res = await fetch(`${baseUrl()}/api/bins/contents`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			const next: Record<string, BinContents> = {};
			for (const entry of Array.isArray(data.bins) ? data.bins : []) {
				if (!entry || typeof entry !== 'object' || typeof entry.bin_key !== 'string') continue;
				next[entry.bin_key] = entry as BinContents;
			}
			contentsByKey = next;
			for (const bin of Object.values(next)) {
				for (const item of bin.items) {
					if (item.part_id) void fetchBricklinkData(item.part_id);
				}
			}
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
		if (homing || movingTo || clearingKey) return;
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
		const label = item.part_id ? `${item.part_id}${item.color_name ? ` · ${item.color_name}` : ''}` : 'Unknown part';
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

	function assignedSetMeta(categoryIds: string[]): { name: string; set_num?: string; img_url?: string } | null {
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
		for (const item of contents?.items ?? []) {
			if (item.part_id) void fetchBricklinkData(item.part_id);
		}
	}

	function openSetChecklist(categoryIds: string[]) {
		if (!categoryIds || categoryIds.length !== 1) return;
		const categoryId = categoryIds[0];
		const target = `${window.location.origin}/bins/set-view/${encodeURIComponent(categoryId)}?base=${encodeURIComponent(baseUrl())}`;
		window.open(target, '_blank', 'noopener,noreferrer');
	}

	async function clearAssignments(
		scope: 'all' | 'layer' | 'bin',
		payload: { layer_index?: number; section_index?: number; bin_index?: number },
		confirmMessage: string,
		busyKey: string
	) {
		if (movingTo || homing || clearingKey) return;
		if (!window.confirm(confirmMessage)) return;

		clearingKey = busyKey;
		statusMsg = '';
		error = null;
		try {
			const res = await fetch(`${baseUrl()}/api/bins/categories/clear`, {
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
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to clear bin assignments';
		} finally {
			clearingKey = null;
		}
	}

	async function toggleLayerEnabled(layerIndex: number, enabled: boolean) {
		if (movingTo || homing || clearingKey || togglingLayerKey !== null) return;
		togglingLayerKey = layerIndex;
		statusMsg = '';
		error = null;
		try {
			const payloadLayers = layers.map((layer) => ({
				bin_count: layer.bin_count,
				enabled: layer.layer_index === layerIndex ? enabled : layer.enabled
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

	onMount(() => {
		void loadLayout();
		void loadBinContents();
		void sortingProfileStore.load(baseUrl()).catch(() => {});
		const interval = setInterval(() => {
			void loadLayout();
			void loadBinContents();
		}, 2000);
		return () => clearInterval(interval);
	});
</script>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-4 sm:p-6">
		<div class="mb-4 flex items-center justify-between gap-4">
			<div>
				<h2 class="text-xl font-bold text-text">Bin Grid</h2>
			</div>
			<div class="flex items-center gap-3">
					<button
						onclick={homeChute}
						disabled={homing || !!movingTo || !!clearingKey}
					class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:opacity-50 disabled:cursor-not-allowed {homing ? 'animate-pulse' : ''}"
					title="Home chute (find endstop)"
				>
					<Home size={16} />
					{homing ? 'Homing...' : 'Home Chute'}
				</button>
				<button
					onclick={() =>
						void clearAssignments(
							'all',
							{},
							'Please make sure all physical bins are empty first. This will remove every learned bin assignment on the machine.',
							'all'
						)}
					disabled={homing || !!movingTo || !!clearingKey}
					class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
					title="Clear all learned bin assignments"
				>
						<Trash2 size={16} />
						{clearingKey === 'all' ? 'Clearing…' : 'Clear All Bins'}
					</button>
			</div>
		</div>

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
					<div class="border border-[#E2E0DB] {!layer.enabled ? 'opacity-60' : ''}">
						<div class="flex items-center justify-between border-b border-[#E2E0DB] bg-surface px-4 py-3">
							<div class="flex items-center gap-3">
								<h3 class="text-base font-semibold text-[#1A1A1A]">
									Layer {layer.layer_index + 1}
									<span class="ml-2 text-sm font-normal text-[#7A7770]">{layer.bin_count} bins</span>
								</h3>
							</div>
							<div class="flex items-center gap-3">
								{#if isActive}
									<span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[#00852B]">
										<span class="inline-block h-2 w-2 bg-[#00852B]"></span>
										Active
									</span>
								{/if}
								<label class="flex items-center">
									<button
										type="button"
										role="switch"
										aria-checked={layer.enabled}
										aria-label={layer.enabled ? `Disable layer ${layer.layer_index + 1}` : `Enable layer ${layer.layer_index + 1}`}
										onclick={() => void toggleLayerEnabled(layer.layer_index, !layer.enabled)}
										disabled={homing || !!movingTo || !!clearingKey || togglingLayerKey !== null}
										class={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${layer.enabled ? 'bg-[#00852B]' : 'bg-[#C9C6BF]'} disabled:cursor-not-allowed disabled:opacity-50`}
									>
										<span class={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${layer.enabled ? 'translate-x-6' : 'translate-x-1'}`}></span>
									</button>
								</label>
								<button
									type="button"
									onclick={() =>
										void clearAssignments(
											'layer',
											{ layer_index: layer.layer_index },
											`Please make sure layer ${layer.layer_index + 1} is physically empty first. This will remove all learned assignments from that layer.`,
											`layer-${layer.layer_index}`
										)}
									disabled={homing || !!movingTo || !!clearingKey || togglingLayerKey !== null}
									class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3.5 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
								>
									<Trash2 size={14} />
									{clearingKey === `layer-${layer.layer_index}` ? 'Clearing…' : 'Clear Layer'}
								</button>
							</div>
						</div>
						<div class="grid grid-cols-6 gap-3 p-3">
							{#each layer.bins as bin}
								{@const key = `${layer.layer_index}-${bin.section_index}-${bin.bin_index}`}
								{@const isCurrent = isCurrentBin(bin) && isActive}
								{@const isMoving = movingTo === key}
								{@const isClearing = clearingKey === `bin-${key}`}
								{@const catLabel = categoryLabel(bin.category_ids)}
								{@const contents = contentsForBin(layer.layer_index, bin)}
								{@const previewItems = cardPreviewItems(contents)}
								{@const setMeta = assignedSetMeta(bin.category_ids)}
								<div class="group relative border border-[#E2E0DB] bg-white">
									<div class="flex items-center justify-between border-b border-[#E2E0DB] bg-surface px-3 py-2">
										<div class="pr-3 text-base font-semibold {isCurrent ? 'text-[#00852B]' : 'text-[#1A1A1A]'}">
											{#if catLabel}
												{bin.global_index + 1}: {catLabel}
											{:else}
												Bin {bin.global_index + 1}
											{/if}
										</div>
										<div class="flex items-center gap-1.5">
											<button
												type="button"
												onclick={() => moveToBin(layer.layer_index, bin.section_index, bin.bin_index)}
												disabled={!!movingTo || !!clearingKey || !layer.enabled}
												class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
												title="Move chute to this bin"
											>
												<Crosshair size={13} />
											</button>
											{#if bin.category_ids.length > 0}
												<button
													type="button"
													onclick={() => void clearAssignments('bin', { layer_index: layer.layer_index, section_index: bin.section_index, bin_index: bin.bin_index }, `Please make sure bin ${bin.global_index + 1} is physically empty first. This will remove the learned assignment for just this bin.`, `bin-${key}`)}
													disabled={!!movingTo || !!clearingKey}
													class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
													title="Clear this bin assignment"
												>
													<Trash2 size={13} />
												</button>
											{/if}
										</div>
									</div>
									<button
										onclick={() => openBinDetails(layer.layer_index, bin)}
										class="relative flex min-h-[6.25rem] w-full flex-col items-start justify-start px-3 py-3 text-left transition-colors {isCurrent ? 'bg-[#00852B]/8 ring-2 ring-inset ring-[#00852B]' : layer.enabled ? 'hover:bg-[#F7F6F3]' : 'cursor-not-allowed'} {isMoving || isClearing ? 'animate-pulse' : ''}"
										title={`Bin ${bin.global_index + 1}${catLabel ? ` — ${catLabel}` : ''}`}
									>
										{#if contents}
											<div class="mt-1 flex min-h-[2.5rem] w-full flex-col gap-3">
												{#if setMeta}
													<div class="relative w-full bg-bg">
														{#if setMeta.img_url}
															<img src={setMeta.img_url} alt={setMeta.name} class="h-28 w-full bg-white object-contain" />
														{/if}
														{#if setMeta.set_num}
															<div class="absolute top-2 right-2 border border-border bg-white/95 px-2 py-1 text-[11px] font-medium text-[#1A1A1A] shadow-sm">{setMeta.set_num}</div>
														{/if}
													</div>
												{/if}
												<div class="grid min-h-[2.5rem] w-full grid-cols-4 gap-2">
													{#each previewItems as piece}
														{@const thumb = previewUrl(piece)}
														<div class="flex h-10 w-10 items-center justify-center bg-bg" title={pieceTooltip(piece)}>
															{#if thumb}
																<img src={thumb} alt={pieceTooltip(piece)} class="h-10 w-10 object-contain" />
															{/if}
														</div>
													{/each}
												</div>
											</div>
										{/if}
									</button>
									{#if !catLabel && !contents}
										<div class="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center opacity-0 transition-opacity group-hover:opacity-100">
											<div class="text-[12px] text-[#8B887F]">No category assigned yet. No recorded pieces yet.</div>
										</div>
									{/if}
									{#if contents}
										<div class="flex items-center justify-between border-t border-[#E2E0DB] px-3 py-2 text-xs text-[#66635C]">
											<div>{contents.unique_item_count} {contents.unique_item_count === 1 ? 'type' : 'types'}</div>
											<div>{contents.piece_count} total</div>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<Modal bind:open={detailsOpen} title={detailsBin ? `Bin ${detailsBin.bin.global_index + 1} Details` : 'Bin Details'} wide={true}>
		{#if detailsBin}
			{@const setMeta = assignedSetMeta(detailsBin.bin.category_ids)}
			<div class="space-y-4">
				<div class="grid gap-4 border border-border bg-surface px-4 py-4 text-sm text-text-muted md:grid-cols-3">
					<div>
						<div class="text-[11px] uppercase tracking-wide">Layer</div>
						<div class="mt-1 text-base font-medium text-text">{detailsBin.layerIndex + 1}</div>
					</div>
					<div>
						<div class="text-[11px] uppercase tracking-wide">Assigned Category</div>
						<div class="mt-1 text-base font-medium text-text">{categoryLabel(detailsBin.bin.category_ids) || 'None'}</div>
					</div>
					<div>
						<div class="text-[11px] uppercase tracking-wide">Recorded Pieces</div>
						<div class="mt-1 text-base font-medium text-text">{detailsBin.contents?.piece_count ?? 0} {(detailsBin.contents?.piece_count ?? 0) === 1 ? 'piece' : 'pieces'}</div>
					</div>
				</div>

				{#if setMeta}
					<div class="border border-border bg-bg p-4">
						<div class="grid gap-4 md:grid-cols-[160px_1fr] md:items-center">
							<div class="flex items-center justify-center bg-surface p-3">
								{#if setMeta.img_url}
									<img src={setMeta.img_url} alt={setMeta.name} class="h-32 w-full object-contain" />
								{/if}
							</div>
							<div>
								<div class="text-lg font-semibold text-text">{setMeta.name}</div>
								{#if setMeta.set_num}
									<div class="mt-1 text-sm text-text-muted">{setMeta.set_num}</div>
								{/if}
								<div class="mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
									<span class="border border-border bg-surface px-2 py-1">{detailsBin.contents?.unique_item_count ?? 0} {(detailsBin.contents?.unique_item_count ?? 0) === 1 ? 'item type' : 'item types'}</span>
									<span class="border border-border bg-surface px-2 py-1">{detailsBin.contents?.piece_count ?? 0} total pieces</span>
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
					<div class="border border-border bg-bg px-4 py-4 text-sm text-text-muted">No detailed piece records for this bin yet.</div>
				{:else}
					<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
						{#each detailsBin.contents.items as item}
							{@const hero = previewUrl(item)}
							<div class="overflow-hidden border border-border bg-bg">
								<div class="relative bg-surface p-4">
									{#if hero}
										<img src={hero} alt={pieceTooltip(item)} class="h-40 w-full object-contain" />
									{/if}
									<div class="absolute top-3 right-3 flex h-10 min-w-10 items-center justify-center bg-[#16A6B6] px-3 text-lg font-semibold text-white shadow-sm">
										{item.count}
									</div>
								</div>
								<div class="px-4 py-3">
									<div class="text-base font-medium text-text">{itemDisplayName(item)}</div>
									<div class="mt-1 text-sm text-text-muted">{itemSecondaryText(item)}</div>
									<div class="mt-2 text-sm text-text-muted">{formatCategoryName(item.category_id) || 'No category'}</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</Modal>
</div>

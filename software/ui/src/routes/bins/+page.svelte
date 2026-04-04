<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';
	import { ArrowRight, Home } from 'lucide-svelte';

	const manager = getMachinesContext();

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

	let layers = $state<LayerInfo[]>([]);
	let currentAngle = $state<number | null>(null);
	let activeLayer = $state<number | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let movingTo = $state<string | null>(null);
	let homing = $state(false);
	let statusMsg = $state('');
	let profileName = $state<string | null>(null);

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
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
			statusMsg = `Moved to ${data.target_angle}\u00b0`;
			activeLayer = layerIndex;
			currentAngle = data.target_angle;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Move failed';
		} finally {
			movingTo = null;
		}
	}

	async function homeChute() {
		if (homing || movingTo) return;
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

	function categoryLabel(categoryIds: string[]): string {
		if (!categoryIds || categoryIds.length === 0) return '';
		return categoryIds
			.map((id) => sortingProfileStore.getCategoryName(id) ?? id)
			.join(', ');
	}

	function binsForSection(layer: LayerInfo, sectionIndex: number): BinInfo[] {
		return layer.bins.filter((b) => b.section_index === sectionIndex);
	}

	onMount(() => {
		void loadLayout();
		void sortingProfileStore.load(baseUrl()).then((p) => { profileName = p.name; }).catch(() => {});
		const interval = setInterval(loadLayout, 2000);
		return () => clearInterval(interval);
	});
</script>

<div class="min-h-screen bg-bg p-4 sm:p-6">
	<AppHeader />

	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<h2 class="text-xl font-bold text-text">Bin Grid</h2>
			<button
				onclick={homeChute}
				disabled={homing || !!movingTo}
				class="flex items-center gap-1.5 border border-border px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:opacity-50 disabled:cursor-not-allowed {homing ? 'animate-pulse' : ''}"
				title="Home chute (find endstop)"
			>
				<Home size={14} />
				{homing ? 'Homing...' : 'Home Chute'}
			</button>
		</div>
		<div class="flex items-center gap-4 text-sm text-text-muted">
			{#if profileName}
				<span>Profile: <span class="text-text">{profileName}</span></span>
			{/if}
			{#if currentAngle !== null}
				<span>Chute: {currentAngle}&deg;</span>
			{/if}
		</div>
	</div>

	<StatusBanner message={statusMsg} variant="success" />
	<StatusBanner message={error ?? ''} variant="error" />

	{#if loading}
		<p class="text-text-muted">Loading bin layout...</p>
	{:else if layers.length === 0}
		<p class="text-text-muted">No storage layers configured.</p>
	{:else}
		<div class="flex flex-col gap-6">
			{#each layers as layer}
				<div class="border border-border">
					<div class="flex items-center justify-between border-b border-border bg-surface px-4 py-2">
						<h3 class="text-sm font-semibold text-text">
							Layer {layer.layer_index + 1}
							<span class="ml-2 text-xs font-normal text-text-muted">
								{layer.bin_count} bins
							</span>
						</h3>
						<div class="flex items-center gap-2">
							{#if activeLayer === layer.layer_index}
								<span class="text-xs font-medium text-[#00852B] dark:text-emerald-400">Active</span>
							{/if}
							{#if !layer.enabled}
								<span class="text-xs text-text-muted">Disabled</span>
							{/if}
						</div>
					</div>
					<div class="flex flex-col gap-2 p-3">
						{#each [0, 1] as rowIdx}
							<div class="flex gap-1">
								{#each [0, 1, 2] as colIdx}
									{@const sectionIdx = rowIdx * 3 + colIdx}
									{@const sectionBins = binsForSection(layer, sectionIdx)}
									{#if sectionBins.length > 0}
										{#if colIdx > 0}
											<div class="w-1 flex-shrink-0 bg-border"></div>
										{/if}
										{#each sectionBins as bin}
											{@const key = `${layer.layer_index}-${bin.section_index}-${bin.bin_index}`}
											{@const isCurrent = isCurrentBin(bin) && activeLayer === layer.layer_index}
											{@const isMoving = movingTo === key}
											{@const catLabel = categoryLabel(bin.category_ids)}
											<button
												onclick={() => moveToBin(layer.layer_index, bin.section_index, bin.bin_index)}
												disabled={!!movingTo || !layer.enabled}
												class="group relative flex min-h-[4rem] flex-1 flex-col items-center justify-center border transition-colors
													{isCurrent
														? 'border-[#00852B] bg-[#00852B]/10 text-[#00852B] dark:border-[#00852B] dark:bg-[#00852B]/20 dark:text-emerald-300'
														: layer.enabled
															? 'border-border bg-bg text-text hover:bg-surface'
															: 'border-border bg-bg text-text-muted opacity-50 cursor-not-allowed'}
													{isMoving ? 'animate-pulse' : ''}"
												title="Layer {layer.layer_index + 1}, Section {bin.section_index + 1}, Bin {bin.bin_index + 1} ({bin.angle}\u00b0){catLabel ? ` — ${catLabel}` : ''}"
											>
												<span class="text-xs font-medium">{bin.global_index + 1}</span>
												{#if catLabel}
													<span class="max-w-full truncate px-1 text-[10px] text-text-muted">{catLabel}</span>
												{:else}
													<span class="text-[10px] text-text-muted">{bin.angle}&deg;</span>
												{/if}
												{#if isCurrent}
													<div class="absolute -top-1 -right-1 h-2 w-2 bg-[#00852B] dark:bg-[#00852B]"></div>
												{/if}
												{#if layer.enabled}
													<div class="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
														<ArrowRight size={14} class="text-text-muted" />
													</div>
												{/if}
											</button>
										{/each}
									{/if}
								{/each}
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

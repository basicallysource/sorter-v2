<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';

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
	let binsLoading = $state(true);

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
			if (!res.ok) return;
			const data = await res.json();
			layers = data.layers ?? [];
			currentAngle = data.current_angle;
			activeLayer = data.active_layer;
		} catch {
			// ignore
		} finally {
			binsLoading = false;
		}
	}

	function isCurrentBin(bin: BinInfo): boolean {
		if (currentAngle === null || activeLayer === null) return false;
		const layer = layers.find((entry) => entry.layer_index === activeLayer);
		if (!layer || !layer.enabled) return false;
		const currentBin = currentBinForLayer(layer);
		return (
			currentBin !== null &&
			currentBin.section_index === bin.section_index &&
			currentBin.bin_index === bin.bin_index
		);
	}

	function angleDistance(a: number, b: number): number {
		const diff = Math.abs(a - b);
		return Math.min(diff, 360 - diff);
	}

	function currentBinForLayer(layer: LayerInfo): BinInfo | null {
		if (currentAngle === null || layer.layer_index !== activeLayer || layer.bins.length === 0) return null;
		let closest = layer.bins[0];
		let closestDistance = angleDistance(closest.angle, currentAngle);
		for (const candidate of layer.bins.slice(1)) {
			const distance = angleDistance(candidate.angle, currentAngle);
			if (distance < closestDistance) {
				closest = candidate;
				closestDistance = distance;
			}
		}
		return closest;
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
		void sortingProfileStore.load(baseUrl()).catch(() => {});
		void loadLayout();
		const interval = setInterval(loadLayout, 2000);
		return () => clearInterval(interval);
	});
</script>

<div class="setup-card-shell border">
	<div class="setup-card-header flex items-center justify-between px-3 py-2">
		<h3 class="text-xs font-semibold uppercase tracking-wide text-[#1A1A1A]">Sorting</h3>
		<div class="flex gap-3">
			<a href="/profiles" class="text-xs text-text-muted hover:text-text">Profiles</a>
			<a href="/bins" class="text-xs text-text-muted hover:text-text">Bins</a>
		</div>
	</div>

	<!-- Compact Bin Grid -->
	{#if binsLoading}
		<div class="px-3 py-3 text-center text-xs text-text-muted">Loading bins...</div>
	{:else if layers.length === 0}
		<div class="px-3 py-3 text-center text-xs text-text-muted">No bins configured</div>
	{:else}
		<div class="flex flex-col gap-3 p-3">
			{#each layers as layer}
				{@const isActive = activeLayer === layer.layer_index}
				<div class="{!layer.enabled ? 'opacity-50' : ''}">
					<div class="mb-1 flex items-center justify-between">
						<span class="text-xs font-semibold uppercase tracking-wide text-text-muted">
							Layer {layer.layer_index + 1}
						</span>
						{#if isActive}
							<span class="flex items-center gap-1 text-xs font-semibold text-success">
								<span class="inline-block h-1.5 w-1.5 bg-success"></span>
								Active
							</span>
						{:else if !layer.enabled}
							<span class="text-xs text-text-muted">Off</span>
						{/if}
					</div>
					<div class="flex flex-col gap-px bg-border">
						{#each [0, 1] as rowIdx}
							{@const rowSections = [0, 1, 2].map(c => binsForSection(layer, rowIdx * 3 + c)).filter(s => s.length > 0)}
							{#if rowSections.flat().length > 0}
								<div class="flex gap-px">
									{#each rowSections as sectionBins, sIdx}
										{#if sIdx > 0}
											<div class="w-0.5 bg-border"></div>
										{/if}
										{#each sectionBins as bin}
											{@const isCurrent = isCurrentBin(bin) && isActive}
											{@const catLabel = categoryLabel(bin.category_ids)}
											<div
												class="flex min-h-[1.75rem] flex-1 items-center justify-center text-xs
													{isCurrent
														? 'bg-success/10 font-bold text-success ring-1 ring-inset ring-success'
														: 'bg-surface text-text'}"
												title="Bin {bin.global_index + 1} ({bin.angle}\u00b0){catLabel ? ` — ${catLabel}` : ''}"
											>
												{bin.global_index + 1}
											</div>
										{/each}
									{/each}
								</div>
							{/if}
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

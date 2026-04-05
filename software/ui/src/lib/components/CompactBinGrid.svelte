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
	let loading = $state(true);

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
			loading = false;
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
		const interval = setInterval(loadLayout, 2000);
		return () => clearInterval(interval);
	});
</script>

<div class="border border-[#E2E0DB] bg-white">
	<div class="flex items-center justify-between border-b border-[#E2E0DB] bg-[#F7F6F3] px-3 py-2">
		<h3 class="text-xs font-semibold uppercase tracking-wide text-[#1A1A1A]">Bins</h3>
		<a href="/bins" class="text-xs text-[#7A7770] hover:text-[#1A1A1A]">View all</a>
	</div>

	{#if loading}
		<div class="px-3 py-4 text-center text-xs text-[#7A7770]">Loading...</div>
	{:else if layers.length === 0}
		<div class="px-3 py-4 text-center text-xs text-[#7A7770]">No bins configured</div>
	{:else}
		<div class="flex flex-col gap-3 p-3">
			{#each layers as layer}
				{@const isActive = activeLayer === layer.layer_index}
				<div class="{!layer.enabled ? 'opacity-50' : ''}">
					<div class="mb-1 flex items-center justify-between">
						<span class="text-[10px] font-semibold uppercase tracking-wide text-[#7A7770]">
							Layer {layer.layer_index + 1}
						</span>
						{#if isActive}
							<span class="flex items-center gap-1 text-[10px] font-semibold text-[#00852B]">
								<span class="inline-block h-1.5 w-1.5 bg-[#00852B]"></span>
								Active
							</span>
						{:else if !layer.enabled}
							<span class="text-[10px] text-[#7A7770]">Off</span>
						{/if}
					</div>
					<div class="flex flex-col gap-px bg-[#E2E0DB]">
						{#each [0, 1] as rowIdx}
							{@const rowSections = [0, 1, 2].map(c => binsForSection(layer, rowIdx * 3 + c)).filter(s => s.length > 0)}
							{#if rowSections.flat().length > 0}
								<div class="flex gap-px">
									{#each rowSections as sectionBins, sIdx}
										{#if sIdx > 0}
											<div class="w-0.5 bg-[#E2E0DB]"></div>
										{/if}
										{#each sectionBins as bin}
											{@const isCurrent = isCurrentBin(bin) && isActive}
											{@const catLabel = categoryLabel(bin.category_ids)}
											<div
												class="flex min-h-[1.75rem] flex-1 items-center justify-center text-[10px]
													{isCurrent
														? 'bg-[#00852B]/10 font-bold text-[#00852B] ring-1 ring-inset ring-[#00852B]'
														: 'bg-white text-[#1A1A1A]'}"
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

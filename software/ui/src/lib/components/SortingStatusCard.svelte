<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore, type SortingProfileMetadata } from '$lib/stores/sortingProfile.svelte';
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

	let profile = $state<SortingProfileMetadata | null>(null);
	let profileLoading = $state(true);
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

	async function loadProfile() {
		try {
			profile = await sortingProfileStore.load(baseUrl());
		} catch {
			// ignore
		} finally {
			profileLoading = false;
		}
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

	const categoryCount = $derived(profile ? Object.keys(profile.categories).length : 0);
	const ruleCount = $derived(profile ? profile.rules.filter(r => !r.disabled).length : 0);
	const syncState = $derived(profile?.sync_state);
	const isSynced = $derived(syncState?.version_number != null && !syncState?.last_error);

	onMount(() => {
		void loadProfile();
		void loadLayout();
		const interval = setInterval(loadLayout, 2000);
		return () => clearInterval(interval);
	});
</script>

<div class="border border-border bg-surface">
	<div class="flex items-center justify-between border-b border-border bg-bg px-3 py-2">
		<h3 class="text-xs font-semibold uppercase tracking-wide text-text">Sorting</h3>
		<div class="flex gap-3">
			<a href="/profiles" class="text-xs text-text-muted hover:text-text">Profiles</a>
			<a href="/bins" class="text-xs text-text-muted hover:text-text">Bins</a>
		</div>
	</div>

	<!-- Active Profile -->
	{#if profileLoading}
		<div class="px-3 py-3 text-center text-xs text-text-muted">Loading profile...</div>
	{:else if !profile}
		<div class="px-3 py-3 text-center text-xs text-text-muted">No profile loaded</div>
	{:else}
		<div class="border-b border-border px-3 py-3">
			<div class="flex items-start gap-2">
				<span class="mt-1 inline-block h-2.5 w-2.5 shrink-0 bg-[#D01012]"></span>
				<div class="min-w-0 flex-1">
					<div class="truncate text-sm font-semibold text-text">{profile.name}</div>
					<div class="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-text-muted">
						{#if syncState?.version_number}
							<span>v{syncState.version_number}</span>
						{/if}
						<span>{categoryCount} categories</span>
						<span>{ruleCount} rules</span>
					</div>
				</div>
			</div>
			{#if syncState}
				<div class="mt-1.5 flex items-center gap-1.5 pl-[1.125rem] text-xs">
					{#if syncState.last_error}
						<span class="inline-block h-1.5 w-1.5 bg-[#D01012]"></span>
						<span class="text-[#D01012]">Sync error</span>
					{:else if isSynced}
						<span class="inline-block h-1.5 w-1.5 bg-[#00852B]"></span>
						<span class="text-[#00852B]">In sync</span>
					{/if}
					{#if syncState.target_name}
						<span class="text-text-muted">&middot; {syncState.target_name}</span>
					{/if}
				</div>
			{/if}
		</div>
	{/if}

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
						<span class="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
							Layer {layer.layer_index + 1}
						</span>
						{#if isActive}
							<span class="flex items-center gap-1 text-[10px] font-semibold text-[#00852B]">
								<span class="inline-block h-1.5 w-1.5 bg-[#00852B]"></span>
								Active
							</span>
						{:else if !layer.enabled}
							<span class="text-[10px] text-text-muted">Off</span>
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
												class="flex min-h-[1.75rem] flex-1 items-center justify-center text-[10px]
													{isCurrent
														? 'bg-[#00852B]/10 font-bold text-[#00852B] ring-1 ring-inset ring-[#00852B]'
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

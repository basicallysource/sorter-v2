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

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-4 sm:p-6">

	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<h2 class="text-xl font-bold text-text">Bin Grid</h2>
			<button
				onclick={homeChute}
				disabled={homing || !!movingTo}
				class="flex items-center gap-1.5 border border-[#E2E0DB] px-3 py-1.5 text-xs font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:opacity-50 disabled:cursor-not-allowed {homing ? 'animate-pulse' : ''}"
				title="Home chute (find endstop)"
			>
				<Home size={14} />
				{homing ? 'Homing...' : 'Home Chute'}
			</button>
		</div>
		<div class="flex items-center gap-4 text-sm text-[#7A7770]">
			{#if profileName}
				<span>Profile: <span class="font-medium text-[#1A1A1A]">{profileName}</span></span>
			{/if}
			{#if currentAngle !== null}
				<span>Chute: <span class="font-mono text-[#1A1A1A]">{currentAngle}&deg;</span></span>
			{/if}
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
					<div class="flex items-center justify-between border-b border-[#E2E0DB] bg-[#F7F6F3] px-4 py-2.5">
						<h3 class="text-sm font-semibold text-[#1A1A1A]">
							Layer {layer.layer_index + 1}
							<span class="ml-2 text-xs font-normal text-[#7A7770]">
								{layer.bin_count} bins
							</span>
						</h3>
						<div class="flex items-center gap-3">
							{#if isActive}
								<span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[#00852B]">
									<span class="inline-block h-2 w-2 bg-[#00852B]"></span>
									Active
								</span>
							{/if}
							{#if !layer.enabled}
								<span class="text-xs font-medium text-[#7A7770]">Disabled</span>
							{/if}
						</div>
					</div>
					<div class="flex flex-col gap-px bg-[#E2E0DB] p-px">
						{#each [0, 1] as rowIdx}
							{@const rowSections = [0, 1, 2].map(c => binsForSection(layer, rowIdx * 3 + c)).filter(s => s.length > 0)}
							{#if rowSections.flat().length > 0}
								<div class="flex gap-px">
									{#each rowSections as sectionBins, sIdx}
										{#if sIdx > 0}
											<div class="w-1 bg-[#E2E0DB]"></div>
										{/if}
										{#each sectionBins as bin}
											{@const key = `${layer.layer_index}-${bin.section_index}-${bin.bin_index}`}
											{@const isCurrent = isCurrentBin(bin) && isActive}
											{@const isMoving = movingTo === key}
											{@const catLabel = categoryLabel(bin.category_ids)}
											<button
												onclick={() => moveToBin(layer.layer_index, bin.section_index, bin.bin_index)}
												disabled={!!movingTo || !layer.enabled}
												class="group relative flex min-h-[4.5rem] flex-1 flex-col items-center justify-center bg-white px-1 py-2 transition-colors
													{isCurrent
														? 'bg-[#00852B]/8 ring-2 ring-inset ring-[#00852B]'
														: layer.enabled
															? 'hover:bg-[#F7F6F3]'
															: 'cursor-not-allowed'}
													{isMoving ? 'animate-pulse' : ''}"
												title="Bin {bin.global_index + 1} ({bin.angle}\u00b0){catLabel ? ` — ${catLabel}` : ''}"
											>
												<span class="text-sm font-bold {isCurrent ? 'text-[#00852B]' : 'text-[#1A1A1A]'}">{bin.global_index + 1}</span>
												{#if catLabel}
													<span class="mt-0.5 max-w-full truncate text-[11px] {isCurrent ? 'text-[#00852B]/70' : 'text-[#7A7770]'}">{catLabel}</span>
												{:else}
													<span class="mt-0.5 font-mono text-[11px] {isCurrent ? 'text-[#00852B]/70' : 'text-[#7A7770]'}">{bin.angle}&deg;</span>
												{/if}
												{#if layer.enabled && !isCurrent}
													<div class="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
														<ArrowRight size={14} class="text-[#7A7770]" />
													</div>
												{/if}
											</button>
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
</div>

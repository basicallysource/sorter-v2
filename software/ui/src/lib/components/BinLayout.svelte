<script lang="ts">
	import { getBinLayout } from '$lib/stores/binLayout.svelte';
	import { getCategoryName } from '$lib/stores/sortingProfile.svelte';

	const binLayout = getBinLayout();

	const DEG_PER_SECTION = 60;
	const PILLAR_WIDTH_DEG = 2.5;
	const USABLE_DEG_PER_SECTION = DEG_PER_SECTION - PILLAR_WIDTH_DEG;

	const SIZE_LABELS: Record<string, string> = {
		small: 'S',
		medium: 'M',
		big: 'L'
	};

	const SIZE_COLORS: Record<string, string> = {
		small: 'bg-blue-500/10 border-blue-500/30',
		medium: 'bg-green-500/10 border-green-500/30',
		big: 'bg-orange-500/10 border-orange-500/30'
	};

	interface SlotItem {
		type: 'bin';
		section_idx: number;
		bin_idx: number;
		angle: number;
		size: string;
		category_id: string | null;
		flex: number;
	}

	interface PillarItem {
		type: 'pillar';
		flex: number;
	}

	type LayoutItem = SlotItem | PillarItem;

	function getAngleForBin(section_idx: number, bin_idx: number, num_bins: number): number {
		const section_start = section_idx * DEG_PER_SECTION + PILLAR_WIDTH_DEG / 2;
		const bin_offset = (bin_idx + 0.5) * (USABLE_DEG_PER_SECTION / num_bins);
		let angle = section_start + bin_offset;
		if (angle > 180) angle -= 360;
		return angle;
	}

	// reorder sections so 0° is in the middle: sections 3,4,5,0,1,2
	// section 3 starts at ~181° -> -179°, section 5 ends near 0°, section 0 starts near 0°, section 2 ends near 180°
	const SECTION_ORDER = [3, 4, 5, 0, 1, 2];

	function buildLayerItems(
		layer: { sections: { bins: { size: string; category_id: string | null }[] }[] }
	): LayoutItem[] {
		const items: LayoutItem[] = [];
		for (let i = 0; i < SECTION_ORDER.length; i++) {
			if (i > 0) {
				items.push({ type: 'pillar', flex: PILLAR_WIDTH_DEG });
			}
			const si = SECTION_ORDER[i];
			const section = layer.sections[si];
			if (!section) continue;
			const num_bins = section.bins.length;
			const bin_deg = USABLE_DEG_PER_SECTION / num_bins;
			for (let bi = 0; bi < num_bins; bi++) {
				const b = section.bins[bi];
				items.push({
					type: 'bin',
					section_idx: si,
					bin_idx: bi,
					angle: getAngleForBin(si, bi, num_bins),
					size: b.size,
					category_id: b.category_id,
					flex: bin_deg
				});
			}
		}
		return items;
	}

	const TICK_DEGREES = [-180, -120, -60, 0, 60, 120, 180];

	function degToPercent(deg: number): number {
		return ((deg + 180) / 360) * 100;
	}
</script>

<div
	class="dark:border-border-dark dark:bg-surface-dark flex flex-col border border-border bg-surface"
>
	<div
		class="dark:bg-surface-dark dark:text-text-dark dark:border-border-dark border-b border-border px-2 py-1 text-sm font-medium text-text"
	>
		Bin Layout
	</div>
	<div class="px-6 py-2">
		{#if binLayout.data}
			<div class="flex flex-col gap-2">
				<!-- degree ruler -->
				<div class="relative h-4">
					<div
						class="dark:border-border-dark absolute right-0 bottom-0 left-0 border-t border-border"
					></div>
					{#each TICK_DEGREES as deg}
						{@const pct = degToPercent(deg)}
						<div
							class="absolute bottom-0 flex flex-col items-center"
							style="left: {pct}%; transform: translateX(-50%)"
						>
							<span
								class="dark:text-text-muted-dark text-[9px] font-mono leading-none text-text-muted"
								>{deg}°</span
							>
							{#if deg !== 0}
								<div
									class="mt-px h-1 w-px bg-border dark:bg-border-dark"
								></div>
							{/if}
						</div>
					{/each}
				</div>

				{#each binLayout.data.layers as layer, layer_idx}
					{@const items = buildLayerItems(layer)}
					<div>
						<div
							class="dark:text-text-muted-dark mb-0.5 text-[10px] font-medium text-text-muted"
						>
							Layer {layer_idx + 1}
						</div>
						<div class="flex">
							{#each items as item}
								{#if item.type === 'pillar'}
									<div
										class="dark:bg-border-dark/30 flex-shrink-0 bg-border/30"
										style="flex: {item.flex}"
									></div>
								{:else}
									{@const label = item.category_id
										? getCategoryName(item.category_id)
										: '—'}
									<div
										class="flex h-10 flex-col items-center justify-center overflow-hidden border text-[9px] {SIZE_COLORS[item.size] ?? 'border-border'}"
										style="flex: {item.flex}"
										title="{item.angle.toFixed(1)}° — L{layer_idx + 1}:S{item.section_idx + 1}:B{item.bin_idx + 1} ({item.size})"
									>
										<span
											class="dark:text-text-dark max-w-full truncate px-0.5 text-text"
											>{label}</span
										>
										<span
											class="dark:text-text-muted-dark font-mono text-text-muted"
											>{SIZE_LABELS[item.size] ?? item.size}</span
										>
									</div>
								{/if}
							{/each}
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="dark:text-text-muted-dark text-center text-xs text-text-muted">
				Loading...
			</div>
		{/if}
	</div>
</div>

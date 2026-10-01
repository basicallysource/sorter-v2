<script lang="ts">
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import type { Snippet } from 'svelte';
	import type { BinInfo } from './types';

	let {
		layerIndex,
		sectionIndex,
		bins,
		enabled,
		toggleDisabled,
		pointDisabled,
		pointing,
		onToggle,
		onPoint,
		binCard
	}: {
		layerIndex: number;
		sectionIndex: number;
		bins: BinInfo[];
		enabled: boolean;
		toggleDisabled: boolean;
		pointDisabled: boolean;
		pointing: boolean;
		onToggle: (enabled: boolean) => void;
		onPoint: () => void;
		binCard: Snippet<[BinInfo]>;
	} = $props();

	const binRangeLabel = $derived.by((): string => {
		if (bins.length === 0) return 'No bins';
		const first = bins[0].global_index + 1;
		const last = bins[bins.length - 1].global_index + 1;
		return bins.length === 1 ? `Bin ${first}` : `Bins ${first}–${last}`;
	});
</script>

<!-- A section of a layer: its name and controls, then its bins. -->
<div class="flex flex-col gap-2">
	<div class="flex items-center justify-between gap-2">
		<div class="flex min-w-0 items-center gap-2 text-sm">
			<span class="shrink-0 font-medium text-ink">Section {sectionIndex + 1}</span>
			<span class="truncate text-ink-muted">{binRangeLabel}</span>
			{#if !enabled}<Badge>Off</Badge>{/if}
		</div>
		<div class="flex shrink-0 items-center gap-2">
			<Switch
				checked={enabled}
				label={enabled
					? `Turn off layer ${layerIndex + 1} section ${sectionIndex + 1}`
					: `Turn on layer ${layerIndex + 1} section ${sectionIndex + 1}`}
				disabled={toggleDisabled}
				onchange={() => onToggle(!enabled)}
			/>
			<Button
				size="sm"
				variant="ghost"
				icon={Crosshair}
				label="Point the chute at section {sectionIndex + 1}"
				loading={pointing}
				disabled={pointDisabled}
				onclick={onPoint}
			/>
		</div>
	</div>
	<div class="grid flex-1 grid-cols-1 gap-2 {bins.length > 1 ? 'sm:grid-cols-2' : ''} {enabled ? '' : 'opacity-60'}">
		{#each bins as bin (bin.global_index)}
			{@render binCard(bin)}
		{/each}
	</div>
</div>

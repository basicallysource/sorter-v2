<script lang="ts">
	import Switch from '$lib/components/ui/Switch.svelte';
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import Spinner from '$lib/components/ui/Spinner.svelte';
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

<div class="flex flex-col border border-line bg-surface {enabled ? '' : 'opacity-60'}">
	<div class="flex items-center justify-between gap-2 border-b border-line bg-well px-3 py-2">
		<div class="flex min-w-0 items-baseline gap-2">
			<span class="shrink-0 text-xs font-semibold text-ink">
				Section {sectionIndex + 1}
			</span>
			<span class="truncate text-xs text-ink-muted">{binRangeLabel}</span>
			{#if !enabled}
				<span class="shrink-0 bg-text-muted px-1.5 py-0.5 text-xs font-semibold text-surface">
					Off
				</span>
			{/if}
		</div>
		<div class="flex shrink-0 items-center gap-1.5">
			<Switch
				checked={enabled}
				label={enabled
					? `Disable layer ${layerIndex + 1} section ${sectionIndex + 1}`
					: `Enable layer ${layerIndex + 1} section ${sectionIndex + 1}`}
				disabled={toggleDisabled}
				onchange={() => onToggle(!enabled)}
			/>
			<button
				type="button"
				onclick={onPoint}
				disabled={pointDisabled}
				class="flex items-center justify-center border border-line bg-surface p-1 text-ink transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
				title="Point chute at section {sectionIndex + 1}"
			>
				{#if pointing}
					<Spinner size={13} />
				{:else}
					<Crosshair size={13} />
				{/if}
			</button>
		</div>
	</div>
	<div class="grid flex-1 gap-3 p-3 {bins.length > 1 ? 'grid-cols-2' : 'grid-cols-1'}">
		{#each bins as bin (bin.global_index)}
			{@render binCard(bin)}
		{/each}
	</div>
</div>

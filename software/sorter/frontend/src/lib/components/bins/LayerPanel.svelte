<script lang="ts">
	import { ToggleSwitch } from '$lib/components/primitives';
	import { ArchiveX, FolderOutput } from 'lucide-svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import BinCard from './BinCard.svelte';
	import SectionGroup from './SectionGroup.svelte';
	import type { BinContents, BinInfo, LayerInfo, SetMeta, SetProgressSummary } from './types';

	let {
		layer,
		isActive,
		layerBusy,
		layerClearingLabel,
		emptyBusy,
		resetBusy,
		niiBusy,
		niiDisabled,
		controlsDisabled,
		clearDisabled,
		sectionToggleDisabled,
		pointDisabled,
		pointingKey,
		contentsLoaded,
		contentsFor,
		setMetaFor,
		setProgressFor,
		isCurrentBin,
		isMovingBin,
		isClearingBin,
		binClearingLabel,
		sectionEnabled,
		moveDisabled,
		searchActive = false,
		searchMatch = () => true,
		onToggleEnabled,
		onEmptyLayer,
		onResetLayer,
		onToggleNii,
		onToggleSection,
		onPointSection,
		onOpenDetails,
		onMoveTo,
		onEmptyBin,
		onResetBin
	}: {
		layer: LayerInfo;
		isActive: boolean;
		layerBusy: boolean;
		layerClearingLabel: string;
		emptyBusy: boolean;
		resetBusy: boolean;
		niiBusy: boolean;
		niiDisabled: boolean;
		controlsDisabled: boolean;
		clearDisabled: boolean;
		sectionToggleDisabled: boolean;
		pointDisabled: boolean;
		pointingKey: string | null;
		contentsLoaded: boolean;
		contentsFor: (bin: BinInfo) => BinContents | null;
		setMetaFor: (bin: BinInfo) => SetMeta | null;
		setProgressFor: (bin: BinInfo) => SetProgressSummary | null;
		isCurrentBin: (bin: BinInfo) => boolean;
		isMovingBin: (bin: BinInfo) => boolean;
		isClearingBin: (bin: BinInfo) => boolean;
		binClearingLabel: (bin: BinInfo) => string;
		sectionEnabled: (sectionIndex: number) => boolean;
		moveDisabled: boolean;
		searchActive?: boolean;
		searchMatch?: (bin: BinInfo) => boolean;
		onToggleEnabled: (enabled: boolean) => void;
		onEmptyLayer: () => void;
		onResetLayer: () => void;
		onToggleNii: (enabled: boolean) => void;
		onToggleSection: (sectionIndex: number, enabled: boolean) => void;
		onPointSection: (sectionIndex: number) => void;
		onOpenDetails: (bin: BinInfo) => void;
		onMoveTo: (bin: BinInfo) => void;
		onEmptyBin: (bin: BinInfo) => void;
		onResetBin: (bin: BinInfo) => void;
	} = $props();

	const layerNii = $derived(layer.bins.length > 0 && layer.bins.every((b) => b.not_in_inventory));

	// The physical layer is a ring split into sections, each holding a few bins.
	// Group the flat bins list back into sections so the grid mirrors the machine.
	const sections = $derived.by((): { sectionIndex: number; bins: BinInfo[] }[] => {
		const bySection = new Map<number, BinInfo[]>();
		for (const bin of layer.bins) {
			const list = bySection.get(bin.section_index) ?? [];
			list.push(bin);
			bySection.set(bin.section_index, list);
		}
		return Array.from({ length: layer.section_count }, (_, sectionIndex) => ({
			sectionIndex,
			bins: (bySection.get(sectionIndex) ?? []).sort((a, b) => a.bin_index - b.bin_index)
		}));
	});
</script>

<div class="relative border border-border {!layer.enabled ? 'opacity-60' : ''}">
	{#if layerBusy}
		<div class="absolute inset-0 z-20 flex items-center justify-center bg-surface/78 backdrop-blur-[1px]">
			<div class="flex items-center gap-3 border border-border bg-surface px-4 py-3 shadow-sm">
				<Spinner size={16} class="text-primary" />
				<div class="text-sm font-medium text-text">{layerClearingLabel}</div>
			</div>
		</div>
	{/if}
	<div class="flex items-center justify-between border-b border-border bg-bg px-4 py-3">
		<div class="flex items-center gap-3">
			<h3 class="text-base font-semibold text-text">
				Layer {layer.layer_index + 1}
				<span class="ml-2 text-sm font-normal text-text-muted">
					{layer.section_count} sections · {layer.bin_count} bins
				</span>
			</h3>
		</div>
		<div class="flex items-center gap-3">
			{#if isActive}
				<span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-success">
					<span class="inline-block h-2 w-2 bg-success"></span>
					Active
				</span>
			{/if}
			<ToggleSwitch
				checked={layer.enabled}
				label={layer.enabled ? `Disable layer ${layer.layer_index + 1}` : `Enable layer ${layer.layer_index + 1}`}
				disabled={controlsDisabled}
				onToggle={() => onToggleEnabled(!layer.enabled)}
			/>
			<button
				type="button"
				onclick={onEmptyLayer}
				disabled={clearDisabled}
				class="flex items-center gap-2 border border-border bg-surface px-3.5 py-2 text-sm font-medium text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				<FolderOutput size={14} />
				{emptyBusy ? 'Emptying…' : 'Empty Layer'}
			</button>
			<button
				type="button"
				onclick={onResetLayer}
				disabled={clearDisabled}
				class="flex items-center gap-2 border border-border bg-surface px-3.5 py-2 text-sm font-medium text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				<ArchiveX size={14} />
				{resetBusy ? 'Resetting…' : 'Reset Layer'}
			</button>
			<button
				type="button"
				onclick={() => onToggleNii(!layerNii)}
				disabled={niiDisabled}
				title="Route pieces not in the active BrickLink inventory (.bsx) into this layer's bins"
				class="flex items-center gap-2 border px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 {layerNii
					? 'border-warning bg-warning/[0.12] text-warning'
					: 'border-border bg-surface text-text hover:bg-bg'}"
			>
				{niiBusy ? 'Saving…' : layerNii ? 'Not-in-inventory: ON' : 'Not-in-inventory mode'}
			</button>
		</div>
	</div>
	<div class="grid grid-cols-1 gap-3 p-3 md:grid-cols-2 2xl:grid-cols-3">
		{#each sections as section (section.sectionIndex)}
			<SectionGroup
				layerIndex={layer.layer_index}
				sectionIndex={section.sectionIndex}
				bins={section.bins}
				enabled={sectionEnabled(section.sectionIndex)}
				toggleDisabled={sectionToggleDisabled}
				{pointDisabled}
				pointing={pointingKey === `point-${section.sectionIndex}`}
				onToggle={(enabled) => onToggleSection(section.sectionIndex, enabled)}
				onPoint={() => onPointSection(section.sectionIndex)}
			>
				{#snippet binCard(bin: BinInfo)}
					{@const clearing = isClearingBin(bin)}
					<BinCard
						{bin}
						layerEnabled={layer.enabled}
						maxPiecesPerBin={layer.max_pieces_per_bin}
						isCurrent={isCurrentBin(bin)}
						isMoving={isMovingBin(bin)}
						isClearing={clearing}
						clearingLabel={binClearingLabel(bin)}
						sectionOn={sectionEnabled(bin.section_index)}
						contents={contentsFor(bin)}
						{contentsLoaded}
						setMeta={setMetaFor(bin)}
						setProgress={setProgressFor(bin)}
						moveDisabled={moveDisabled || !layer.enabled}
						clearDisabled={clearDisabled || clearing}
						searchState={searchActive ? (searchMatch(bin) ? 'match' : 'miss') : 'off'}
						onOpenDetails={() => onOpenDetails(bin)}
						onMoveTo={() => onMoveTo(bin)}
						onEmpty={() => onEmptyBin(bin)}
						onReset={() => onResetBin(bin)}
					/>
				{/snippet}
			</SectionGroup>
		{/each}
	</div>
</div>

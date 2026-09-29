<script lang="ts">
	import ArchiveX from '@lucide/svelte/icons/archive-x';
	import FolderOutput from '@lucide/svelte/icons/folder-output';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
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

<Panel
	title="Layer {layer.layer_index + 1}"
	description="{layer.section_count} sections · {layer.bin_count} bins"
	class="relative"
>
	{#snippet actions()}
		{#if isActive}<Badge tone="success" dot>Active</Badge>{/if}
		<Switch
			checked={layer.enabled}
			label={layer.enabled
				? `Turn off layer ${layer.layer_index + 1}`
				: `Turn on layer ${layer.layer_index + 1}`}
			disabled={controlsDisabled}
			onchange={() => onToggleEnabled(!layer.enabled)}
		/>
	{/snippet}
	{#if layerBusy}
		<div class="absolute inset-0 z-20 flex items-center justify-center gap-3 bg-surface/85">
			<Spinner size={16} class="text-primary-ink" />
			<span class="text-sm font-medium text-ink">{layerClearingLabel}</span>
		</div>
	{/if}
	<div class="flex flex-col gap-4 {layer.enabled ? '' : 'opacity-60'}">
		<div class="flex flex-wrap items-center gap-2">
			<Button size="sm" icon={FolderOutput} loading={emptyBusy} disabled={clearDisabled} onclick={onEmptyLayer}>
				{emptyBusy ? 'Emptying…' : 'Empty the layer'}
			</Button>
			<Button size="sm" icon={ArchiveX} loading={resetBusy} disabled={clearDisabled} onclick={onResetLayer}>
				{resetBusy ? 'Resetting…' : 'Reset the layer'}
			</Button>
			<Button
				size="sm"
				variant={layerNii ? 'primary' : 'secondary'}
				loading={niiBusy}
				disabled={niiDisabled}
				onclick={() => onToggleNii(!layerNii)}
			>
				{niiBusy ? 'Saving…' : layerNii ? 'Not-in-inventory mode is on' : 'Not-in-inventory mode'}
			</Button>
			<span class="text-sm text-ink-muted">
				Not-in-inventory mode sends pieces missing from the active BrickLink inventory (.bsx) to this layer.
			</span>
		</div>
		<div class="grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-2 2xl:grid-cols-3">
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
</Panel>

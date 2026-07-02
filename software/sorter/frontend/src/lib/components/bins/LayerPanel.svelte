<script lang="ts">
	import { ToggleSwitch } from '$lib/components/primitives';
	import { ArchiveX, Crosshair, FolderOutput, Loader2 } from 'lucide-svelte';
	import BinCard from './BinCard.svelte';
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
</script>

<div class="relative border border-[#E2E0DB] {!layer.enabled ? 'opacity-60' : ''}">
	{#if layerBusy}
		<div class="absolute inset-0 z-20 flex items-center justify-center bg-white/78 backdrop-blur-[1px]">
			<div class="flex items-center gap-3 border border-[#E2E0DB] bg-white px-4 py-3 shadow-sm">
				<Loader2 size={16} class="animate-spin text-primary" />
				<div class="text-sm font-medium text-[#1A1A1A]">{layerClearingLabel}</div>
			</div>
		</div>
	{/if}
	<div class="flex items-center justify-between border-b border-[#E2E0DB] bg-surface px-4 py-3">
		<div class="flex items-center gap-3">
			<h3 class="text-base font-semibold text-[#1A1A1A]">
				Layer {layer.layer_index + 1}
				<span class="ml-2 text-sm font-normal text-[#7A7770]">{layer.bin_count} bins</span>
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
				class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3.5 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
			>
				<FolderOutput size={14} />
				{emptyBusy ? 'Emptying…' : 'Empty Layer'}
			</button>
			<button
				type="button"
				onclick={onResetLayer}
				disabled={clearDisabled}
				class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3.5 py-2 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
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
					: 'border-[#E2E0DB] bg-white text-[#1A1A1A] hover:bg-[#F7F6F3]'}"
			>
				{niiBusy ? 'Saving…' : layerNii ? 'Not-in-inventory: ON' : 'Not-in-inventory mode'}
			</button>
		</div>
	</div>
	<div class="flex flex-wrap items-center gap-2 border-b border-[#E2E0DB] bg-[#FAFAF8] px-3 py-2">
		<span class="text-xs font-semibold uppercase tracking-wide text-[#7A7770]">Sections</span>
		{#each Array(layer.section_count) as _unused, sectionIndex}
			{@const secOn = sectionEnabled(sectionIndex)}
			<div class="flex items-center gap-1.5 border border-[#E2E0DB] {secOn ? 'bg-white' : 'bg-[#F2F0EB]'} px-2 py-1">
				<span class="text-sm {secOn ? 'text-[#1A1A1A]' : 'text-[#9A968E]'}">S{sectionIndex + 1}</span>
				<ToggleSwitch
					checked={secOn}
					size="sm"
					label={secOn
						? `Disable layer ${layer.layer_index + 1} section ${sectionIndex + 1}`
						: `Enable layer ${layer.layer_index + 1} section ${sectionIndex + 1}`}
					disabled={sectionToggleDisabled}
					onToggle={() => onToggleSection(sectionIndex, !secOn)}
				/>
				<button
					type="button"
					onclick={() => onPointSection(sectionIndex)}
					disabled={pointDisabled}
					class="flex items-center justify-center border border-[#E2E0DB] bg-white p-1 text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
					title="Point chute at section {sectionIndex + 1}"
				>
					{#if pointingKey === `point-${sectionIndex}`}
						<Loader2 size={13} class="animate-spin" />
					{:else}
						<Crosshair size={13} />
					{/if}
				</button>
			</div>
		{/each}
	</div>
	<div class="grid grid-cols-6 gap-3 p-3">
		{#each layer.bins as bin (bin.global_index)}
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
				onOpenDetails={() => onOpenDetails(bin)}
				onMoveTo={() => onMoveTo(bin)}
				onEmpty={() => onEmptyBin(bin)}
				onReset={() => onResetBin(bin)}
			/>
		{/each}
	</div>
</div>

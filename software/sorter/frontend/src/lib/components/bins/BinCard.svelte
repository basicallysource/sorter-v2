<script lang="ts">
	import PieceThumb from '$lib/components/PieceThumb.svelte';
	import { Skeleton } from '$lib/components/primitives';
	import { ArchiveX, Crosshair, FolderOutput, Loader2, Tag } from 'lucide-svelte';
	import { categoryLabel, pieceTooltip, previewUrl } from './pieces';
	import type { BinContentItem, BinContents, BinInfo, SetMeta, SetProgressSummary } from './types';

	let {
		bin,
		layerEnabled,
		maxPiecesPerBin,
		isCurrent,
		isMoving,
		isClearing,
		clearingLabel,
		sectionOn,
		contents,
		contentsLoaded,
		setMeta,
		setProgress,
		moveDisabled,
		clearDisabled,
		onOpenDetails,
		onMoveTo,
		onEmpty,
		onReset
	}: {
		bin: BinInfo;
		layerEnabled: boolean;
		maxPiecesPerBin: number | null;
		isCurrent: boolean;
		isMoving: boolean;
		isClearing: boolean;
		clearingLabel: string;
		sectionOn: boolean;
		contents: BinContents | null;
		contentsLoaded: boolean;
		setMeta: SetMeta | null;
		setProgress: SetProgressSummary | null;
		moveDisabled: boolean;
		clearDisabled: boolean;
		onOpenDetails: () => void;
		onMoveTo: () => void;
		onEmpty: () => void;
		onReset: () => void;
	} = $props();

	const catLabel = $derived(categoryLabel(bin.category_ids));

	const previewItems = $derived.by((): BinContentItem[] => {
		if (!contents) return [];
		if (Array.isArray(contents.recent_pieces) && contents.recent_pieces.length > 0) {
			return contents.recent_pieces.slice(0, 8);
		}
		return [...contents.items]
			.sort((a, b) => Number(b.last_distributed_at ?? 0) - Number(a.last_distributed_at ?? 0))
			.slice(0, 8);
	});
</script>

<div class="group relative flex h-full flex-col border border-[#E2E0DB] bg-white {sectionOn ? '' : 'opacity-50'}">
	{#if !sectionOn}
		<div class="absolute right-1 top-1 z-10 bg-[#9A968E] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-white">
			Section off
		</div>
	{/if}
	{#if isClearing}
		<div class="absolute inset-0 z-20 flex items-center justify-center bg-white/82 backdrop-blur-[1px]">
			<div class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3 py-2 shadow-sm">
				<Loader2 size={14} class="animate-spin text-primary" />
				<span class="text-xs font-semibold uppercase tracking-wide text-[#1A1A1A]">{clearingLabel}</span>
			</div>
		</div>
	{/if}
	<div class="flex items-start justify-between gap-2 border-b border-[#E2E0DB] bg-surface px-3 py-2">
		<div class="flex min-h-[2.5rem] min-w-0 items-start gap-2 pt-0.5">
			<span class="shrink-0 border border-[#E2E0DB] bg-white px-1.5 py-0.5 text-xs font-semibold tabular-nums {isCurrent ? 'text-success' : 'text-[#66635C]'}">
				{bin.global_index + 1}
			</span>
			<span
				class="line-clamp-2 min-w-0 text-sm font-semibold leading-5 {catLabel ? (isCurrent ? 'text-success' : 'text-[#1A1A1A]') : 'font-normal italic text-[#9A968E]'}"
				title={catLabel || 'No category assigned'}
			>
				{catLabel || 'Unassigned'}
			</span>
		</div>
		<div class="flex shrink-0 items-center gap-1.5">
			<button
				type="button"
				onclick={onOpenDetails}
				class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A]"
				title="Assign categories to this bin"
			>
				<Tag size={13} />
			</button>
			<button
				type="button"
				onclick={onMoveTo}
				disabled={moveDisabled}
				class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
				title="Move chute to this bin"
			>
				<Crosshair size={13} />
			</button>
			{#if contents && contents.piece_count > 0}
				<button
					type="button"
					onclick={onEmpty}
					disabled={clearDisabled}
					class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
					title="Empty this bin but keep assignment"
				>
					<FolderOutput size={13} />
				</button>
			{/if}
			{#if bin.category_ids.length > 0}
				<button
					type="button"
					onclick={onReset}
					disabled={clearDisabled}
					class="border border-[#E2E0DB] bg-white/95 p-1.5 text-[#7A7770] transition-colors hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-50"
					title="Reset this bin and clear assignment"
				>
					<ArchiveX size={13} />
				</button>
			{/if}
		</div>
	</div>
	{#if maxPiecesPerBin && maxPiecesPerBin > 0}
		{@const fillCount = contents?.piece_count ?? 0}
		{@const fillPct = Math.min(100, Math.max(0, (fillCount / maxPiecesPerBin) * 100))}
		{@const isFull = fillCount >= maxPiecesPerBin}
		{@const isNearFull = fillCount / maxPiecesPerBin >= 0.85 && !isFull}
		<div
			class="relative h-4 w-full overflow-hidden border-b border-[#E2E0DB] bg-[#F0EFEB]"
			title="{fillCount} / {maxPiecesPerBin} pieces"
		>
			<div
				class="absolute inset-y-0 left-0 transition-all {isFull ? 'bg-danger' : isNearFull ? 'bg-warning' : 'bg-success'}"
				style="width: {fillPct}%"
			></div>
			<div class="relative flex h-full items-center justify-center text-xs font-semibold tabular-nums text-[#1A1A1A] mix-blend-luminosity">
				{fillCount} / {maxPiecesPerBin}
			</div>
		</div>
	{/if}
	<button
		onclick={onOpenDetails}
		class="relative flex min-h-[6.25rem] w-full flex-1 flex-col items-start justify-start px-3 py-3 text-left transition-colors {isCurrent ? 'bg-success/8 ring-2 ring-inset ring-success' : layerEnabled ? 'hover:bg-[#F7F6F3]' : 'cursor-not-allowed'} {isMoving || isClearing ? 'animate-pulse' : ''}"
		title={`Bin ${bin.global_index + 1}${catLabel ? ` — ${catLabel}` : ''}`}
	>
		{#if !contentsLoaded}
			<div class="mt-1 grid w-full grid-cols-4 gap-2">
				{#each Array(4) as _unused}
					<Skeleton class="aspect-square w-full" />
				{/each}
			</div>
		{:else if contents && previewItems.length > 0}
			<div class="mt-1 flex w-full flex-col gap-3">
				{#if setMeta}
					<div class="relative w-full border border-[#E2E0DB] bg-bg">
						{#if setMeta.img_url}
							<img src={setMeta.img_url} alt={setMeta.name} class="block max-h-[400px] w-full bg-white object-contain" />
						{/if}
						{#if setMeta.set_num}
							<div class="absolute top-2 right-2 border border-border bg-white/95 px-2 py-1 text-xs font-medium text-[#1A1A1A] shadow-sm">{setMeta.set_num}</div>
						{/if}
					</div>
				{/if}
				<div class="grid w-full grid-cols-4 gap-2">
					{#each previewItems as piece}
						<div class="aspect-square w-full border border-[#EEECE7] bg-[#FAFAF8]" title={pieceTooltip(piece)}>
							<PieceThumb src={previewUrl(piece)} alt={pieceTooltip(piece)} fallbackText={piece.part_id ?? '?'} />
						</div>
					{/each}
				</div>
			</div>
		{:else}
			<div class="flex w-full flex-1 items-center justify-center py-4 text-sm text-[#9A968E]">Empty</div>
		{/if}
	</button>
	{#if setProgress && setProgress.total_needed > 0}
		{@const clampedPct = Math.min(100, Math.max(0, setProgress.pct))}
		{@const isDone = setProgress.total_found >= setProgress.total_needed}
		<div
			class="relative h-5 w-full overflow-hidden border-t border-[#E2E0DB] bg-[#F0EFEB]"
			title="{setProgress.total_found} of {setProgress.total_needed} parts found"
		>
			<div
				class="absolute inset-y-0 left-0 transition-all {isDone ? 'bg-success' : 'bg-primary'}"
				style="width: {clampedPct}%"
			></div>
			<div class="relative flex h-full items-center justify-center text-xs font-semibold tabular-nums text-[#1A1A1A] mix-blend-luminosity">
				{setProgress.total_found} / {setProgress.total_needed} parts
			</div>
		</div>
	{/if}
	<div class="flex items-center justify-between border-t border-[#E2E0DB] px-3 py-2 text-xs text-[#66635C]">
		{#if !contentsLoaded}
			<Skeleton class="h-4 w-16" />
			<Skeleton class="h-4 w-12" />
		{:else}
			<div>{contents?.unique_item_count ?? 0} {(contents?.unique_item_count ?? 0) === 1 ? 'type' : 'types'}</div>
			<div>{contents?.piece_count ?? 0} total</div>
		{/if}
	</div>
</div>

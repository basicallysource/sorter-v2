<script lang="ts">
	import PieceThumb from '$lib/components/PieceThumb.svelte';
	import { Skeleton } from '$lib/components/primitives';
	import { ArchiveX, Crosshair, FolderOutput, Loader2, Tag } from 'lucide-svelte';
	import { categoryLabel, formatLastSeen, formatRelativeTime, pieceTooltip, previewUrl } from './pieces';
	import QuantityBadge from './QuantityBadge.svelte';
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
		searchState = 'off',
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
		searchState?: 'off' | 'match' | 'miss';
		onOpenDetails: () => void;
		onMoveTo: () => void;
		onEmpty: () => void;
		onReset: () => void;
	} = $props();

	const catLabel = $derived(categoryLabel(bin.category_ids));

	// Server-grouped items: unique part+color(+status) rows carrying `count`,
	// already sorted count DESC — one thumb per kind, quantity shown as a badge.
	const previewItems = $derived.by((): BinContentItem[] => {
		if (!contents) return [];
		return contents.items.slice(0, 8);
	});

	const lastDropRelative = $derived(formatRelativeTime(contents?.last_distributed_at));

	function itemTooltip(item: BinContentItem): string {
		return item.count > 1 ? `${pieceTooltip(item)} ×${item.count}` : pieceTooltip(item);
	}
</script>

<div
	class="group relative flex h-full flex-col border bg-surface {searchState === 'match'
		? 'border-primary ring-2 ring-primary'
		: 'border-border'} {searchState === 'miss' ? 'opacity-40' : ''} {sectionOn ? '' : 'opacity-50'}"
>
	{#if !sectionOn}
		<div class="absolute right-1 top-1 z-10 bg-text-muted px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-surface">
			Section off
		</div>
	{/if}
	{#if isClearing}
		<div class="absolute inset-0 z-20 flex items-center justify-center bg-surface/82 backdrop-blur-[1px]">
			<div class="flex items-center gap-2 border border-border bg-surface px-3 py-2 shadow-sm">
				<Loader2 size={14} class="animate-spin text-primary" />
				<span class="text-xs font-semibold uppercase tracking-wide text-text">{clearingLabel}</span>
			</div>
		</div>
	{/if}
	<div class="flex items-start justify-between gap-2 border-b border-border bg-bg px-3 py-2">
		<div class="flex min-h-[2.5rem] min-w-0 items-start gap-2 pt-0.5">
			<span
				class="shrink-0 border border-border bg-surface px-1.5 py-0.5 text-xs font-semibold tabular-nums {isCurrent ? 'text-success' : 'text-text-muted'}"
				title={`Bin ${bin.global_index + 1} — section ${bin.section_index + 1}, slot ${bin.bin_index + 1}`}
			>
				{bin.global_index + 1}
			</span>
			<span
				class="line-clamp-2 min-w-0 text-sm font-semibold leading-5 {catLabel ? (isCurrent ? 'text-success' : 'text-text') : 'font-normal italic text-text-muted'}"
				title={catLabel || 'No category assigned'}
			>
				{catLabel || 'Unassigned'}
			</span>
		</div>
		<div class="flex shrink-0 items-center gap-1.5">
			<button
				type="button"
				onclick={onOpenDetails}
				class="border border-border bg-surface/95 p-1.5 text-text-muted transition-colors hover:bg-bg hover:text-text"
				title="Assign categories to this bin"
			>
				<Tag size={13} />
			</button>
			<button
				type="button"
				onclick={onMoveTo}
				disabled={moveDisabled}
				class="border border-border bg-surface/95 p-1.5 text-text-muted transition-colors hover:bg-bg hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
				title="Move chute to this bin"
			>
				<Crosshair size={13} />
			</button>
			{#if contents && contents.piece_count > 0}
				<button
					type="button"
					onclick={onEmpty}
					disabled={clearDisabled}
					class="border border-border bg-surface/95 p-1.5 text-text-muted transition-colors hover:bg-bg hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
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
					class="border border-border bg-surface/95 p-1.5 text-text-muted transition-colors hover:bg-bg hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
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
			class="relative h-4 w-full overflow-hidden border-b border-border bg-bg"
			title="{fillCount} / {maxPiecesPerBin} pieces"
		>
			<div
				class="absolute inset-y-0 left-0 transition-all {isFull ? 'bg-danger' : isNearFull ? 'bg-warning' : 'bg-success'}"
				style="width: {fillPct}%"
			></div>
			<div class="relative flex h-full items-center justify-center text-xs font-semibold tabular-nums text-text mix-blend-luminosity">
				{fillCount} / {maxPiecesPerBin}
			</div>
		</div>
	{/if}
	<button
		onclick={onOpenDetails}
		class="relative flex min-h-[6.25rem] w-full flex-1 flex-col items-start justify-start px-3 py-3 text-left transition-colors {isCurrent ? 'bg-success/8 ring-2 ring-inset ring-success' : layerEnabled ? 'hover:bg-bg' : 'cursor-not-allowed'} {isMoving || isClearing ? 'animate-pulse' : ''}"
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
					<div class="relative w-full border border-border bg-bg">
						{#if setMeta.img_url}
							<img src={setMeta.img_url} alt={setMeta.name} class="block max-h-[400px] w-full bg-surface object-contain" />
						{/if}
						{#if setMeta.set_num}
							<div class="absolute top-2 right-2 border border-border bg-surface/95 px-2 py-1 text-xs font-medium text-text shadow-sm">{setMeta.set_num}</div>
						{/if}
					</div>
				{/if}
				<div class="grid w-full grid-cols-4 gap-2">
					{#each previewItems as item}
						<div class="relative aspect-square w-full border border-border bg-bg" title={itemTooltip(item)}>
							<PieceThumb src={previewUrl(item)} alt={pieceTooltip(item)} fallbackText={item.part_id ?? '?'} />
							{#if item.count > 1}
								<QuantityBadge count={item.count} size="sm" />
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{:else}
			<div class="flex w-full flex-1 items-center justify-center py-4 text-sm text-text-muted">Empty</div>
		{/if}
	</button>
	{#if setProgress && setProgress.total_needed > 0}
		{@const clampedPct = Math.min(100, Math.max(0, setProgress.pct))}
		{@const isDone = setProgress.total_found >= setProgress.total_needed}
		<div
			class="relative h-5 w-full overflow-hidden border-t border-border bg-bg"
			title="{setProgress.total_found} of {setProgress.total_needed} parts found"
		>
			<div
				class="absolute inset-y-0 left-0 transition-all {isDone ? 'bg-success' : 'bg-primary'}"
				style="width: {clampedPct}%"
			></div>
			<div class="relative flex h-full items-center justify-center text-xs font-semibold tabular-nums text-text mix-blend-luminosity">
				{setProgress.total_found} / {setProgress.total_needed} parts
			</div>
		</div>
	{/if}
	<div class="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs text-text-muted">
		{#if !contentsLoaded}
			<Skeleton class="h-4 w-16" />
			<Skeleton class="h-4 w-12" />
		{:else}
			<div>
				{contents?.unique_item_count ?? 0}
				{(contents?.unique_item_count ?? 0) === 1 ? 'type' : 'types'} · {contents?.piece_count ?? 0} total
			</div>
			{#if lastDropRelative}
				<div title={`Last piece ${formatLastSeen(contents?.last_distributed_at)}`}>{lastDropRelative}</div>
			{/if}
		{/if}
	</div>
</div>

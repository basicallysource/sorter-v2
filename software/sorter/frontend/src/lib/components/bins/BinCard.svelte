<script lang="ts">
	import type { Component } from 'svelte';
	import ArchiveX from '@lucide/svelte/icons/archive-x';
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import FolderOutput from '@lucide/svelte/icons/folder-output';
	import Tag from '@lucide/svelte/icons/tag';
	import PieceThumb from '$lib/components/PieceThumb.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
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

	type MenuEntry =
		| 'separator'
		| {
				label: string;
				icon: Component<{ size?: number; class?: string }>;
				onselect: () => void;
				disabled?: boolean;
				danger?: boolean;
		  };
	// Emptying or resetting a bin is rare, so it lives in a menu; the reset,
	// which drops the bin's assignment, comes last.
	const menuItems = $derived.by((): MenuEntry[] => {
		const items: MenuEntry[] = [{ label: 'Assign categories', icon: Tag, onselect: onOpenDetails }];
		if (contents && contents.piece_count > 0) {
			items.push({ label: 'Empty this bin', icon: FolderOutput, onselect: onEmpty, disabled: clearDisabled });
		}
		if (bin.category_ids.length > 0) {
			items.push('separator', {
				label: 'Reset this bin and clear its assignment',
				icon: ArchiveX,
				onselect: onReset,
				disabled: clearDisabled,
				danger: true
			});
		}
		return items;
	});

	function itemTooltip(item: BinContentItem): string {
		return item.count > 1 ? `${pieceTooltip(item)} ×${item.count}` : pieceTooltip(item);
	}
</script>

<div
	class="relative flex h-full flex-col gap-2 rounded-control p-2.5 transition-colors {isCurrent
		? 'bg-success-soft'
		: searchState === 'match'
			? 'bg-primary-soft'
			: 'bg-well'} {searchState === 'miss' ? 'opacity-40' : ''} {sectionOn ? '' : 'opacity-60'}"
>
	{#if isClearing}
		<div class="absolute inset-0 z-20 flex items-center justify-center gap-2 rounded-control bg-surface/85">
			<Spinner size={16} class="text-primary-ink" />
			<span class="text-sm font-medium text-ink">{clearingLabel}</span>
		</div>
	{/if}
	<div class="flex items-start justify-between gap-2">
		<div class="flex min-w-0 items-start gap-2 pt-1">
			<span
				class="num shrink-0 rounded-badge bg-hover px-1.5 text-xs leading-5 font-medium {isCurrent
					? 'text-success-ink'
					: 'text-ink-muted'}"
				title={`Bin ${bin.global_index + 1}: section ${bin.section_index + 1}, slot ${bin.bin_index + 1}`}
			>
				{bin.global_index + 1}
			</span>
			<span
				class="line-clamp-2 min-w-0 text-sm leading-5 {catLabel
					? `font-medium ${isCurrent ? 'text-success-ink' : 'text-ink'}`
					: 'text-ink-muted'}"
				title={catLabel || 'No category assigned'}
			>
				{catLabel || 'Unassigned'}
			</span>
		</div>
		<div class="-mr-1 flex shrink-0 items-center">
			<Button
				size="sm"
				variant="ghost"
				icon={Crosshair}
				label="Move the chute to bin {bin.global_index + 1}"
				loading={isMoving}
				disabled={moveDisabled}
				onclick={onMoveTo}
			/>
			<Menu label="Bin {bin.global_index + 1} actions" items={menuItems}>
				{#snippet trigger(props)}
					<Button
						{...props}
						size="sm"
						variant="ghost"
						icon={Ellipsis}
						label="More actions for bin {bin.global_index + 1}"
					/>
				{/snippet}
			</Menu>
		</div>
	</div>
	{#if maxPiecesPerBin && maxPiecesPerBin > 0}
		{@const fillCount = contents?.piece_count ?? 0}
		{@const isFull = fillCount >= maxPiecesPerBin}
		{@const isNearFull = fillCount / maxPiecesPerBin >= 0.85 && !isFull}
		<div class="flex items-center gap-2">
			<div class="min-w-0 flex-1">
				<ProgressBar
					value={fillCount}
					max={maxPiecesPerBin}
					label="Pieces in the bin"
					tone={isFull ? 'danger' : isNearFull ? 'warning' : 'primary'}
				/>
			</div>
			<span class="num shrink-0 text-xs text-ink-muted">{fillCount} / {maxPiecesPerBin}</span>
		</div>
	{/if}
	<button
		type="button"
		onclick={onOpenDetails}
		aria-label="Open bin {bin.global_index + 1}{catLabel ? `, ${catLabel}` : ''}"
		class="-mx-1 flex min-h-[5rem] flex-1 flex-col items-stretch justify-start rounded-item p-1 text-left transition-colors {layerEnabled
			? 'hover:bg-hover'
			: 'cursor-not-allowed'}"
	>
		{#if !contentsLoaded}
			<div class="grid w-full grid-cols-4 gap-2">
				{#each Array(4) as _unused}
					<Skeleton class="aspect-square w-full" />
				{/each}
			</div>
		{:else if contents && previewItems.length > 0}
			<div class="flex w-full flex-col gap-2">
				{#if setMeta}
					<div class="relative w-full overflow-hidden rounded-item bg-surface">
						{#if setMeta.img_url}
							<img src={setMeta.img_url} alt={setMeta.name} class="block max-h-[400px] w-full object-contain" />
						{/if}
						{#if setMeta.set_num}
							<span class="dark num absolute top-1 right-1 rounded-badge bg-scrim px-1.5 text-xs font-medium text-ink">
								{setMeta.set_num}
							</span>
						{/if}
					</div>
				{/if}
				<div class="grid w-full grid-cols-4 gap-2">
					{#each previewItems as item}
						<div class="relative aspect-square w-full overflow-hidden rounded-item bg-surface" title={itemTooltip(item)}>
							<PieceThumb src={previewUrl(item)} alt={pieceTooltip(item)} fallbackText={item.part_id ?? '?'} />
							{#if item.count > 1}
								<QuantityBadge count={item.count} size="sm" />
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{:else}
			<div class="flex w-full flex-1 items-center justify-center py-4 text-sm text-ink-muted">Empty</div>
		{/if}
	</button>
	{#if setProgress && setProgress.total_needed > 0}
		{@const isDone = setProgress.total_found >= setProgress.total_needed}
		<div class="flex items-center gap-2">
			<div class="min-w-0 flex-1">
				<ProgressBar
					value={setProgress.total_found}
					max={setProgress.total_needed}
					label="Parts of the set found"
					tone={isDone ? 'success' : 'primary'}
				/>
			</div>
			<span class="num shrink-0 text-xs text-ink-muted">
				{setProgress.total_found} / {setProgress.total_needed} parts
			</span>
		</div>
	{/if}
	<div class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-xs text-ink-muted">
		{#if !contentsLoaded}
			<Skeleton class="h-4 w-16" />
			<Skeleton class="h-4 w-12" />
		{:else}
			<div class="num">
				{contents?.unique_item_count ?? 0}
				{(contents?.unique_item_count ?? 0) === 1 ? 'type' : 'types'} · {contents?.piece_count ?? 0} total
			</div>
			{#if !sectionOn}
				<Badge>Section off</Badge>
			{:else if lastDropRelative}
				<div title={`Last piece ${formatLastSeen(contents?.last_distributed_at)}`}>{lastDropRelative}</div>
			{/if}
		{/if}
	</div>
</div>

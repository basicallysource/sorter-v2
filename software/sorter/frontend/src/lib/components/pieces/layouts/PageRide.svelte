<script lang="ts">
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Lane from './Lane.svelte';
	import PageParts from './PageParts.svelte';
	import PredictionsTable from './PredictionsTable.svelte';
	import ReviewPreview from './ReviewPreview.svelte';
	import { CHANNEL_NAMES, confidenceClass, RIDE, shotsOf, shotTime, type PieceView } from './model';

	// A piece's page told as its ride through the machine, left to right: what
	// each channel saw and when, what the pictures were taken for, and where
	// the piece went. Five columns of one width; a channel's pictures sit in a
	// block of slots that is the same size in every column.
	let { piece }: { piece: PieceView } = $props();

	const used = $derived(piece.shots.filter((shot) => shot.used).length);
</script>

{#snippet head(step: string, title: string, at: string | null)}
	<div class="flex items-baseline justify-between gap-2">
		<span class="flex min-w-0 items-baseline gap-2">
			<span class="font-mono text-xs text-ink-muted">{step}</span>
			<span class="truncate text-sm font-semibold text-ink">{title}</span>
		</span>
		{#if at}<span class="num shrink-0 text-xs text-ink-muted">{at}</span>{/if}
	</div>
{/snippet}

<Panel flush>
	<div class="@container">
		<div
			class="grid grid-cols-[minmax(0,1fr)] divide-y divide-line @5xl:grid-cols-5 @5xl:divide-x @5xl:divide-y-0"
		>
			{#each RIDE as channel (channel)}
				{@const shots = shotsOf(piece, channel)}
				<section class="flex min-w-0 flex-col gap-3 p-(--pad-panel)">
					{@render head(channel, CHANNEL_NAMES[channel], shotTime(shots[0]))}
					{#if shots.length === 0}
						<p class="text-sm text-ink-faint">No pictures linked to this piece here.</p>
					{:else}
						<Lane {shots} size={3.5} cols={3} rows={3} />
						<p class="text-xs text-ink-muted">
							{shots.length}
							{shots.length === 1 ? 'picture' : 'pictures'}{channel === 'C4'
								? `, ${used} produced the result`
								: ', found by the link model'}
						</p>
					{/if}
				</section>
			{/each}

			<section class="flex min-w-0 flex-col gap-3 p-(--pad-panel)">
				{@render head('4', 'Identified', piece.whenExact)}
				<div class="flex items-start gap-3">
					<ImageZoom src={piece.reference} label="Brickognize's picture of this part">
						<PartImage src={piece.reference} class="size-[7.375rem] shrink-0" />
					</ImageZoom>
				</div>
				<div class="flex min-w-0 flex-col gap-1">
					<span class="text-sm font-semibold text-ink">{piece.name}</span>
					<span class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
						{#if piece.partId}<span class="font-mono text-ink-muted">{piece.partId}</span>{/if}
						{#if piece.partPct != null}
							<span class="num font-medium {confidenceClass(piece.partPct)}">
								{piece.partPct}%
							</span>
						{/if}
						<PieceStatusBadge status={piece.summary.classification_status} />
					</span>
					{#if piece.color}
						<span class="flex items-center gap-2 text-sm">
							<ColorChip name={piece.color.name} rgb={piece.color.hex} class="text-ink" />
							{#if piece.colorPct != null}
								<span class="num font-medium {confidenceClass(piece.colorPct)}">
									{piece.colorPct}%
								</span>
							{/if}
						</span>
					{/if}
				</div>
			</section>

			<section class="flex min-w-0 flex-col gap-3 p-(--pad-panel)">
				{@render head('5', 'Binned', null)}
				<span class="font-mono text-2xl leading-none text-ink">{piece.bin ?? '—'}</span>
				<dl class="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
					{#if piece.value}
						<dt class="text-ink-muted">Value</dt>
						<dd class="num text-ink">{piece.value}</dd>
					{/if}
					{#if piece.partBy}
						<dt class="text-ink-muted">Part by</dt>
						<dd class="truncate text-ink">{piece.partBy}</dd>
					{/if}
					{#if piece.colorBy}
						<dt class="text-ink-muted">Color by</dt>
						<dd class="truncate text-ink">{piece.colorBy}</dd>
					{/if}
				</dl>
			</section>
		</div>
	</div>
</Panel>

<div class="@container">
	<div
		class="grid grid-cols-[minmax(0,1fr)] items-start gap-(--gap-panels) @5xl:grid-cols-[minmax(0,1fr)_27rem]"
	>
		<PredictionsTable {piece} />
		<Panel title="Review">
			<ReviewPreview {piece} layout="compact" />
		</Panel>
	</div>
</div>

<PageParts />

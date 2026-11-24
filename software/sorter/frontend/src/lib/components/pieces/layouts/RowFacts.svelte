<script lang="ts">
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import { confidenceClass, type PieceView } from './model';

	// What the machine decided about a piece, for a row of the records: its
	// name, then its color and how sure the part is, then where and when. Every
	// line is one line: a long name is cut short, never wrapped, so the row
	// keeps its height. `line` puts all of it on one line.
	let { piece, line = false }: { piece: PieceView; line?: boolean } = $props();

	const used = $derived(piece.shots.filter((shot) => shot.used).length);
</script>

{#snippet name()}
	<a
		href={`/tracked/${piece.uuid}`}
		class="min-w-0 truncate text-sm font-semibold text-ink hover:underline"
	>
		{piece.name}
	</a>
	{#if piece.partId}
		<span class="shrink-0 font-mono text-xs text-ink-muted">{piece.partId}</span>
	{/if}
{/snippet}

{#snippet decided()}
	{#if piece.color}
		<ColorChip name={piece.color.name} rgb={piece.color.hex} class="shrink-0 text-sm text-ink" />
	{/if}
	{#if piece.partPct != null}
		<span
			class="num shrink-0 text-sm font-medium {confidenceClass(piece.partPct)}"
			title="How sure the identification was"
		>
			{piece.partPct}%
		</span>
	{/if}
	{#if piece.value}
		<span class="num shrink-0 text-sm text-ink" title="BrickLink moving-average price">
			{piece.value}
		</span>
	{/if}
{/snippet}

{#snippet where()}
	{#if piece.bin}<span class="shrink-0 font-mono">{piece.bin}</span>{/if}
	{#if piece.when}<span class="num shrink-0">{piece.when}</span>{/if}
	<span class="num shrink-0" title="Pictures that produced the result, of all of the piece">
		{used} of {piece.shots.length} pictures used
	</span>
{/snippet}

{#if line}
	<div class="flex min-w-0 items-center gap-x-3 overflow-hidden whitespace-nowrap">
		{@render name()}
		<PieceStatusBadge status={piece.summary.classification_status} />
		{@render decided()}
		<span class="flex min-w-0 items-center gap-x-3 overflow-hidden text-xs text-ink-muted">
			{@render where()}
		</span>
	</div>
{:else}
	<div class="flex min-w-0 flex-col gap-1">
		<div class="flex min-w-0 items-baseline gap-2">{@render name()}</div>
		<div class="flex min-w-0 items-center gap-x-3 overflow-hidden whitespace-nowrap">
			<PieceStatusBadge status={piece.summary.classification_status} />
			{@render decided()}
		</div>
		<div
			class="flex min-w-0 items-center gap-x-3 overflow-hidden text-xs whitespace-nowrap text-ink-muted"
		>
			{@render where()}
		</div>
	</div>
{/if}

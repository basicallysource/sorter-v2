<script lang="ts">
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Lane from './Lane.svelte';
	import ReviewPreview from './ReviewPreview.svelte';
	import RowFacts from './RowFacts.svelte';
	import { CHANNELS, shotsOf, type Channel, type PieceView } from './model';

	// A row of the records, laid out as two lines. The first is the pictures:
	// Brickognize's, then every picture of the piece at one size, each channel
	// in its own place across the row. The second is what was decided, and the
	// review on the same line. No picture is shown twice. The slots shrink with
	// the row; a channel that still has no room is left off whole.
	let { piece }: { piece: PieceView } = $props();

	const PLACES: Record<Channel, number> = { C4: 5, C3: 8, C2: 5 };
</script>

<div class="@container px-(--pad-panel) py-3">
	<div class="flex flex-col gap-2.5">
		<div
			class="flex h-[calc(3.5rem*var(--slot-scale)+0.25rem)] flex-wrap items-center gap-x-4 overflow-hidden [--slot-scale:0.45] @4xl:[--slot-scale:0.55] @5xl:[--slot-scale:0.7] @6xl:[--slot-scale:0.8] @[84rem]:[--slot-scale:1]"
		>
			<span class="flex h-full shrink-0 items-center gap-4">
				<ImageZoom src={piece.reference} label="Brickognize's picture of this part">
					<PartImage src={piece.reference} class="size-[calc(3.5rem*var(--slot-scale))]" />
				</ImageZoom>
				<span class="h-[calc(3.5rem*var(--slot-scale))] w-px bg-line"></span>
			</span>
			{#each CHANNELS as channel (channel)}
				<span class="flex h-full shrink-0 items-center gap-1">
					<span class="font-mono text-xs text-ink-muted">{channel}</span>
					<Lane shots={shotsOf(piece, channel)} size={3.5} cols={PLACES[channel]} />
				</span>
			{/each}
		</div>
		<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
			<div class="min-w-0 flex-1"><RowFacts {piece} line /></div>
			<ReviewPreview {piece} layout="line" />
		</div>
	</div>
</div>

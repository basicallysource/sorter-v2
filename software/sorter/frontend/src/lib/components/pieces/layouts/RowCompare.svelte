<script lang="ts">
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import { pictures } from './fit.svelte';
	import Lane from './Lane.svelte';
	import ReviewPreview from './ReviewPreview.svelte';
	import RowFacts from './RowFacts.svelte';
	import Slot from './Slot.svelte';
	import { bestShot, CHANNELS, shotsOf, type Channel, type PieceView } from './model';

	// A row of the records, laid out for the one question a reviewer answers:
	// is this the part? The camera's picture and Brickognize's sit side by side
	// at one size. Every other picture is small, on one line, each channel in
	// its own place.
	let { piece }: { piece: PieceView } = $props();

	const best = $derived(bestShot(piece));
	// How many slots each channel has on the line, always. The slots shrink
	// with the row; a channel that still has no room is left off whole, so a
	// picture is never cut in half.
	const PLACES: Record<Channel, number> = { C4: 5, C3: 6, C2: 4 };
</script>

<div class="@container px-(--pad-panel) py-3">
	<div
		class="grid grid-cols-[minmax(0,1fr)] items-center gap-x-5 gap-y-3 @3xl:grid-cols-[13.75rem_minmax(0,1fr)] @6xl:grid-cols-[13.75rem_minmax(0,1fr)_24rem]"
	>
		<div class="flex gap-3">
			<div class="flex flex-col items-center gap-1">
				{#if best}
					<Slot
						shot={best}
						size={6.5}
						fit={pictures.fit === 'fill' ? 'bare' : pictures.fit}
						mark={false}
					/>
				{:else}
					<span class="block size-[6.5rem] rounded-item bg-well"></span>
				{/if}
				<span class="text-xs text-ink-muted">Camera</span>
			</div>
			<div class="flex flex-col items-center gap-1">
				<ImageZoom src={piece.reference} label="Brickognize's picture of this part">
					<PartImage src={piece.reference} class="size-[6.5rem]" />
				</ImageZoom>
				<span class="text-xs text-ink-muted">Brickognize</span>
			</div>
		</div>

		<div class="flex min-w-0 flex-col gap-2.5">
			<RowFacts {piece} />
			<div
				class="flex h-[calc(2rem*var(--slot-scale)+0.25rem)] flex-wrap items-center gap-x-3 overflow-hidden [--slot-scale:0.6] @4xl:[--slot-scale:0.75] @6xl:[--slot-scale:0.6] @7xl:[--slot-scale:0.75] @[84rem]:[--slot-scale:1]"
			>
				{#each CHANNELS as channel (channel)}
					<span class="flex h-full shrink-0 items-center gap-1">
						<span class="font-mono text-xs text-ink-muted">{channel}</span>
						<Lane shots={shotsOf(piece, channel)} size={2} cols={PLACES[channel]} />
					</span>
				{/each}
			</div>
		</div>

		<div class="@3xl:col-span-2 @6xl:col-span-1">
			<ReviewPreview {piece} layout="compact" />
		</div>
	</div>
</div>

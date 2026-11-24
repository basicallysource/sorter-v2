<script lang="ts">
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Lane from './Lane.svelte';
	import ReviewPreview from './ReviewPreview.svelte';
	import RowFacts from './RowFacts.svelte';
	import Slot from './Slot.svelte';
	import { bestShot, type PieceView } from './model';

	// A row of the records at a third of the height, for going through many
	// pieces: the camera's picture and Brickognize's, what was decided on two
	// short lines, every picture in a small block, and the review on one line.
	let { piece }: { piece: PieceView } = $props();

	const best = $derived(bestShot(piece));
</script>

<div class="@container px-(--pad-panel) py-2">
	<div
		class="grid grid-cols-[minmax(0,1fr)] items-center gap-x-5 gap-y-2 @3xl:grid-cols-[6.375rem_minmax(0,1fr)_auto] @7xl:grid-cols-[6.375rem_minmax(0,1fr)_auto_auto]"
	>
		<div class="flex gap-1.5">
			{#if best}
				<Slot shot={best} size={3} mark={false} />
			{:else}
				<span class="block size-12 rounded-item bg-well"></span>
			{/if}
			<ImageZoom src={piece.reference} label="Brickognize's picture of this part">
				<PartImage src={piece.reference} class="size-12" />
			</ImageZoom>
		</div>
		<RowFacts {piece} />
		<Lane shots={piece.shots} size={1.5} cols={9} rows={2} />
		<div class="@3xl:col-span-3 @7xl:col-span-1">
			<ReviewPreview {piece} layout="line" />
		</div>
	</div>
</div>

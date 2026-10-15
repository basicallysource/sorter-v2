<script lang="ts">
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import type { Frame } from './types';

	// The frames the camera took of a piece, in a row that wraps: small, so a
	// burst of eight reads at a glance, each enlarged under the pointer
	// (ImageZoom) and opening the full-size viewer when clicked. The frames that
	// produced the result are tinted, with the channel they came from and, when
	// it was measured, their sharpness over the corner.
	let {
		frames,
		onZoom
	}: {
		frames: Frame[];
		onZoom: (src: string, label: string) => void;
	} = $props();
</script>

<div class="flex flex-wrap gap-1.5">
	{#each frames as frame (frame.key)}
		<ImageZoom src={frame.src} label={frame.label}>
			<button
				type="button"
				aria-label={frame.label}
				class="relative block size-[4.75rem] shrink-0 rounded-item p-1 transition-colors {frame.used
					? 'bg-primary-soft'
					: 'hover:bg-hover'}"
				onclick={() => onZoom(frame.src, frame.label)}
			>
				<PartImage src={frame.src} class="size-full" />
				<span
					class="dark absolute bottom-1 left-1 rounded-badge bg-scrim px-1 text-xs font-medium text-ink"
				>
					{frame.channel}
				</span>
				{#if frame.sharpness}
					<span
						class="dark num absolute top-1 right-1 rounded-badge bg-scrim px-1 text-xs font-medium text-ink"
					>
						{frame.sharpness}
					</span>
				{/if}
			</button>
		</ImageZoom>
	{/each}
</div>

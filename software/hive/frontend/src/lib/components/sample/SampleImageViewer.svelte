<script lang="ts">
	import { api } from '$lib/api';
	import type { SampleDetail, SampleSwatchRun } from '$lib/api';
	import ReviewImageViewer from '$lib/components/review/ReviewImageViewer.svelte';
	import SwatchOverlay from './SwatchOverlay.svelte';

	type Bbox = { x: number; y: number; w: number; h: number };
	type PaletteColor = { stroke: string; fill: string };
	type ViewMode = 'image' | 'full_frame' | 'channel_crop' | 'overlay' | 'annotate';

	interface Props {
		sample: SampleDetail;
		activeView: ViewMode;
		effectiveImageUrl: string;
		proposalBoxes: Bbox[];
		showBboxOverlay: boolean;
		imageNaturalWidth: number;
		imageNaturalHeight: number;
		proposalColor: (index: number) => PaletteColor;
		onload: (event: Event) => void;
		// The palette swatches to draw, on the full frame they were read from.
		swatchRun?: SampleSwatchRun | null;
	}

	let {
		sample,
		activeView,
		effectiveImageUrl,
		proposalBoxes,
		showBboxOverlay,
		imageNaturalWidth,
		imageNaturalHeight,
		proposalColor,
		onload,
		swatchRun = null
	}: Props = $props();

	// The image view shows the full frame too when the sample's image is the
	// frame itself (a synced sample): its size says so.
	const swatchesOnImage = $derived(
		swatchRun != null && imageNaturalWidth === swatchRun.frame_width && imageNaturalHeight === swatchRun.frame_height
	);
</script>

{#if activeView === 'image'}
	<div class="relative">
		<ReviewImageViewer
			imageUrl={effectiveImageUrl}
			imageAlt="Sample"
			{proposalBoxes}
			{showBboxOverlay}
			{imageNaturalWidth}
			{imageNaturalHeight}
			{proposalColor}
			{onload}
		/>
		{#if swatchRun && swatchesOnImage}<SwatchOverlay run={swatchRun} />{/if}
	</div>
{:else}
	{@const other = {
		full_frame: sample.has_full_frame ? { src: api.sampleFullFrameUrl(sample.id), alt: 'Full frame' } : null,
		channel_crop: sample.has_channel_geometry ? { src: api.sampleChannelCropUrl(sample.id), alt: 'Channel crop' } : null,
		overlay: sample.has_overlay ? { src: api.sampleOverlayUrl(sample.id), alt: 'Overlay' } : null,
		annotate: null
	}[activeView]}
	{#if other}
		<div class="relative overflow-hidden rounded-panel bg-media">
			<img src={other.src} alt={other.alt} class="w-full" />
			{#if swatchRun && activeView === 'full_frame'}<SwatchOverlay run={swatchRun} />{/if}
		</div>
	{/if}
{/if}

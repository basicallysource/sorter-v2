<script lang="ts">
	import { api } from '$lib/api';
	import type { SampleDetail } from '$lib/api';
	import ReviewImageViewer from '$lib/components/review/ReviewImageViewer.svelte';

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
		onload
	}: Props = $props();
</script>

{#if activeView === 'image'}
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
{:else}
	{@const other = {
		full_frame: sample.has_full_frame ? { src: api.sampleFullFrameUrl(sample.id), alt: 'Full frame' } : null,
		channel_crop: sample.has_channel_geometry ? { src: api.sampleChannelCropUrl(sample.id), alt: 'Channel crop' } : null,
		overlay: sample.has_overlay ? { src: api.sampleOverlayUrl(sample.id), alt: 'Overlay' } : null,
		annotate: null
	}[activeView]}
	{#if other}
		<div class="overflow-hidden rounded-panel bg-media"><img src={other.src} alt={other.alt} class="w-full" /></div>
	{/if}
{/if}

<script lang="ts">
	import { api } from '$lib/api';
	import type { SampleDetail } from '$lib/api';

	type Bbox = { x: number; y: number; w: number; h: number };
	type PaletteColor = { stroke: string; fill: string };
	type ViewMode = 'image' | 'full_frame' | 'overlay' | 'annotate';

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

<div class="overflow-hidden border border-border bg-gray-950">
	<div class="relative">
		{#if activeView === 'image'}
			<img
				src={effectiveImageUrl}
				alt="Sample"
				class="w-full"
				{onload}
			/>
		{:else if activeView === 'full_frame' && sample.has_full_frame}
			<img
				src={api.sampleFullFrameUrl(sample.id)}
				alt="Full frame"
				class="w-full"
			/>
		{:else if activeView === 'overlay' && sample.has_overlay}
			<img
				src={api.sampleOverlayUrl(sample.id)}
				alt="Overlay"
				class="w-full"
			/>
		{/if}

		{#if showBboxOverlay && activeView === 'image' && imageNaturalWidth > 0 && proposalBoxes.length > 0}
			<svg
				class="absolute inset-0 h-full w-full pointer-events-none"
				viewBox="0 0 {imageNaturalWidth} {imageNaturalHeight}"
				preserveAspectRatio="xMidYMid meet"
			>
				{#each proposalBoxes as bbox, i}
					{@const color = proposalColor(i)}
					<rect
						x={bbox.x} y={bbox.y} width={bbox.w} height={bbox.h}
						fill={color.fill}
						stroke={color.stroke}
						stroke-width="2"
					/>
					<rect
						x={bbox.x} y={bbox.y - 18} width={52} height={18}
						fill="rgba(0,0,0,0.6)" rx="2"
					/>
					<text
						x={bbox.x + 5} y={bbox.y - 5}
						fill={color.stroke}
						font-size="11"
						font-family="monospace"
					>box {i + 1}</text>
				{/each}
			</svg>
		{/if}
	</div>
</div>

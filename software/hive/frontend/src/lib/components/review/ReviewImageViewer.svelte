<script lang="ts">
	type Bbox = { x: number; y: number; w: number; h: number };
	type PaletteColor = { stroke: string; fill: string };

	interface Props {
		imageUrl: string;
		imageAlt: string;
		proposalBoxes: Bbox[];
		showBboxOverlay: boolean;
		imageNaturalWidth: number;
		imageNaturalHeight: number;
		proposalColor: (index: number) => PaletteColor;
		onload: (event: Event) => void;
	}

	let {
		imageUrl,
		imageAlt,
		proposalBoxes,
		showBboxOverlay,
		imageNaturalWidth,
		imageNaturalHeight,
		proposalColor,
		onload
	}: Props = $props();
</script>

<div class="relative overflow-hidden rounded-panel bg-media">
	<img src={imageUrl} alt={imageAlt} class="w-full" {onload} />
	{#if showBboxOverlay && imageNaturalWidth > 0 && proposalBoxes.length > 0}
		<svg
			class="pointer-events-none absolute inset-0 size-full"
			viewBox="0 0 {imageNaturalWidth} {imageNaturalHeight}"
			preserveAspectRatio="xMidYMid meet"
		>
			{#each proposalBoxes as bbox, index (index)}
				{@const color = proposalColor(index)}
				<rect x={bbox.x} y={bbox.y} width={bbox.w} height={bbox.h} fill={color.fill} stroke={color.stroke} stroke-width="2" />
				<rect x={bbox.x} y={bbox.y - 18} width={52} height={18} class="fill-(--scrim)" />
				<text x={bbox.x + 5} y={bbox.y - 5} fill={color.stroke} font-size="11" class="font-mono">box {index + 1}</text>
			{/each}
		</svg>
	{/if}
</div>

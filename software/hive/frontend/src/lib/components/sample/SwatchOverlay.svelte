<script lang="ts">
	import type { SampleSwatchRun } from '$lib/api';

	// The colour reference palette's tiles as one swatch run found them, drawn
	// over the full frame they were read from. Sits in a positioned box the
	// size of the picture; the viewBox is the frame, so boxes land on the tiles.
	let { run }: { run: SampleSwatchRun } = $props();

	const size = $derived(Math.max(run.frame_width, run.frame_height) / 90);

	function rgb(values: number[]): string {
		return `rgb(${values.map((v) => Math.round(v)).join(' ')})`;
	}
</script>

<svg
	class="pointer-events-none absolute inset-0 size-full"
	viewBox="0 0 {run.frame_width} {run.frame_height}"
	preserveAspectRatio="xMidYMid meet"
	aria-label={`${run.swatch_count} palette swatches`}
>
	{#each run.swatches as s (s.position)}
		{@const [x0, y0, x1, y1] = s.box}
		{@const left = s.centre[0] > run.frame_width / 2}
		{@const label = `${s.position} ${s.colour}`}
		{@const labelWidth = size * (label.length * 0.62 + 2.4)}
		{@const lx = left ? x0 - size * 0.5 - labelWidth : x1 + size * 0.5}
		<!-- Flagged readings in yellow, clean ones in green, from the boxes' palette over photos (bbox-helpers.ts). -->
		<rect
			x={x0}
			y={y0}
			width={x1 - x0}
			height={y1 - y0}
			fill="none"
			stroke={s.flags.length ? '#eab308' : '#22c55e'}
			stroke-width="2"
			vector-effect="non-scaling-stroke"
		/>
		<rect x={lx} y={y0} width={labelWidth} height={size * 1.5} class="fill-(--scrim)" />
		<rect x={lx + size * 0.3} y={y0 + size * 0.3} width={size * 0.9} height={size * 0.9} fill={rgb(s.rgb)} stroke="white" stroke-width="1" vector-effect="non-scaling-stroke" />
		<text x={lx + size * 1.5} y={y0 + size * 1.1} fill="white" font-size={size} class="font-mono">{label}</text>
	{/each}
</svg>

<script lang="ts">
	interface Props {
		values: number[];
		height?: number;
		showAxis?: boolean;
	}

	const { values, height = 80, showAxis = true }: Props = $props();

	const gridlines = [0, 25, 50, 75, 100];

	const points = $derived.by(() => {
		if (values.length === 0) return '';
		if (values.length === 1) {
			const y = 100 - Math.min(1, Math.max(0, values[0])) * 100;
			return `0,${y} 100,${y}`;
		}
		return values
			.map((v, i) => {
				const x = (i / (values.length - 1)) * 100;
				const y = 100 - Math.min(1, Math.max(0, v)) * 100;
				return `${x.toFixed(2)},${y.toFixed(2)}`;
			})
			.join(' ');
	});

	const areaPath = $derived.by(() => {
		if (!points) return '';
		const segs = points.split(' ').map((p) => `L ${p}`).join(' ');
		return `M 0,100 ${segs} L 100,100 Z`;
	});

	const last = $derived(values.length > 0 ? values[values.length - 1] : 0);
	const color = $derived(
		last >= 1 ? '#00852B' : last >= 0.6 ? '#7AAE3D' : last >= 0.3 ? '#FFA500' : '#D01012'
	);
</script>

<div class="relative w-full" class:pr-8={showAxis} style="height: {height}px;">
	<svg viewBox="0 0 100 100" preserveAspectRatio="none" class="block h-full w-full">
		{#each gridlines as g (g)}
			<line
				x1="0"
				x2="100"
				y1={100 - g}
				y2={100 - g}
				stroke="#D1CFCA"
				stroke-width="1"
				stroke-dasharray="2,2"
				vector-effect="non-scaling-stroke"
				opacity={g === 0 || g === 100 ? 0.7 : 0.4}
			/>
		{/each}
		{#if values.length > 0}
			<path d={areaPath} fill={color} fill-opacity="0.14" />
			<polyline
				fill="none"
				stroke={color}
				stroke-width="1.5"
				stroke-linejoin="round"
				stroke-linecap="round"
				points={points}
				vector-effect="non-scaling-stroke"
			/>
		{/if}
	</svg>
	{#if showAxis}
		{#each gridlines as g (g)}
			<span
				class="pointer-events-none absolute right-0 -translate-y-1/2 pl-1 text-[9px] tabular-nums text-text-muted"
				style="top: {100 - g}%;"
			>
				{g}%
			</span>
		{/each}
	{/if}
</div>

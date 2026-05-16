<script lang="ts">
	import type { SampleDiversityBucketFills } from '$lib/api';

	interface Props {
		bucketFills: SampleDiversityBucketFills;
		bucketKeys: string[];
		coverage: number;
		size?: number;
		showLabels?: boolean;
	}

	const { bucketFills, bucketKeys, coverage, size = 200, showLabels = true }: Props = $props();

	const labelPad = 14;
	const cx = $derived(size / 2);
	const cy = $derived(size / 2);
	const outerR = $derived(size / 2 - labelPad);
	const innerR = $derived(outerR * 0.42);
	const labelR = $derived(outerR + labelPad * 0.55);

	const segments = $derived.by(() => {
		const n = bucketKeys.length;
		const sweep = (Math.PI * 2) / n;
		const gap = 0.012;
		return bucketKeys.map((key, i) => {
			const start = -Math.PI / 2 + i * sweep + gap / 2;
			const end = start + sweep - gap;
			const raw = bucketFills[key];
			const ignored = raw === null || raw === undefined;
			const fill = ignored ? 0 : Math.min(1, Math.max(0, raw as number));
			return { key, start, end, fill, ignored };
		});
	});

	function arc(
		startAngle: number,
		endAngle: number,
		rOuter: number,
		rInner: number
	): string {
		const x1 = cx + rOuter * Math.cos(startAngle);
		const y1 = cy + rOuter * Math.sin(startAngle);
		const x2 = cx + rOuter * Math.cos(endAngle);
		const y2 = cy + rOuter * Math.sin(endAngle);
		const x3 = cx + rInner * Math.cos(endAngle);
		const y3 = cy + rInner * Math.sin(endAngle);
		const x4 = cx + rInner * Math.cos(startAngle);
		const y4 = cy + rInner * Math.sin(startAngle);
		const large = endAngle - startAngle > Math.PI ? 1 : 0;
		return `M ${x1} ${y1} A ${rOuter} ${rOuter} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${rInner} ${rInner} 0 ${large} 0 ${x4} ${y4} Z`;
	}

	function fillColor(fill: number): string {
		if (fill >= 1) return '#00852B';
		if (fill >= 0.6) return '#7AAE3D';
		if (fill >= 0.3) return '#FFA500';
		if (fill > 0) return '#D01012';
		return '#E2E0DB';
	}

	const coveragePct = $derived(Math.round(coverage * 100));
</script>

<div class="inline-flex flex-col items-center">
	<svg width={size} height={size} viewBox="0 0 {size} {size}" role="img" overflow="visible">
		{#each segments as seg (seg.key)}
			{@const filledOuter = innerR + (outerR - innerR) * seg.fill}
			<path
				d={arc(seg.start, seg.end, outerR, innerR)}
				fill={seg.ignored ? '#EBE9E4' : '#F2F0EB'}
				opacity={seg.ignored ? 0.6 : 1}
			/>
			{#if !seg.ignored && seg.fill > 0}
				<path d={arc(seg.start, seg.end, filledOuter, innerR)} fill={fillColor(seg.fill)} />
			{/if}
			{#if showLabels}
				{@const mid = (seg.start + seg.end) / 2}
				{@const lx = cx + labelR * Math.cos(mid)}
				{@const ly = cy + labelR * Math.sin(mid)}
				<text
					x={lx}
					y={ly}
					text-anchor="middle"
					dominant-baseline="middle"
					class="text-[10px] fill-text-muted tabular-nums"
					opacity={seg.ignored ? 0.4 : 1}
					text-decoration={seg.ignored ? 'line-through' : 'none'}
				>
					{seg.key}
				</text>
			{/if}
		{/each}
		<text
			x={cx}
			y={cy - 4}
			text-anchor="middle"
			dominant-baseline="middle"
			class="text-xl font-bold tabular-nums fill-text"
		>
			{coveragePct}%
		</text>
		<text
			x={cx}
			y={cy + 12}
			text-anchor="middle"
			dominant-baseline="middle"
			class="text-[10px] fill-text-muted uppercase tracking-wider"
		>
			diversity
		</text>
	</svg>
</div>

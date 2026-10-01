<script lang="ts">
	// A time series as SVG, drawn here (line with its area, or bars): no chart
	// library. The design system's docs/components.md, Charts.
	export type SeriesPoint = { date: string; value: number };

	let {
		points,
		kind = 'line',
		color = 'var(--primary)',
		formatValue = (v: number) => v.toLocaleString()
	}: {
		points: SeriesPoint[];
		kind?: 'line' | 'bar';
		color?: string;
		formatValue?: (v: number) => string;
	} = $props();

	// One drawing unit is one pixel, so a label is 12px at any width (a viewBox scaled to
	// a phone would shrink it below that). Until the width is measured, a typical one.
	let measured = $state(560);
	const W = $derived(Math.max(240, measured));
	const H = 170;
	const M = { top: 10, right: 10, bottom: 24, left: 48 };
	const innerW = $derived(W - M.left - M.right);
	const innerH = H - M.top - M.bottom;

	function parseDay(day: string): number {
		const t = Date.parse(`${day}T00:00:00`);
		return Number.isNaN(t) ? 0 : t;
	}

	// Round the axis max up to 1/2/5 × 10^n so gridline labels read clean.
	function niceMax(v: number): number {
		if (v <= 0) return 1;
		const pow = Math.pow(10, Math.floor(Math.log10(v)));
		for (const step of [1, 2, 5, 10]) {
			if (v <= step * pow) return step * pow;
		}
		return 10 * pow;
	}

	const sorted = $derived([...points].sort((a, b) => parseDay(a.date) - parseDay(b.date)));
	const yMax = $derived(niceMax(Math.max(0, ...sorted.map((p) => p.value))));
	const t0 = $derived(sorted.length > 0 ? parseDay(sorted[0].date) : 0);
	const t1 = $derived(sorted.length > 0 ? parseDay(sorted[sorted.length - 1].date) : 1);
	const span = $derived(Math.max(1, t1 - t0));

	function xOf(day: string): number {
		if (sorted.length <= 1) return M.left + innerW / 2;
		return M.left + ((parseDay(day) - t0) / span) * innerW;
	}

	function yOf(value: number): number {
		return M.top + innerH - (Math.min(value, yMax) / yMax) * innerH;
	}

	const linePath = $derived(
		sorted.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.date).toFixed(1)},${yOf(p.value).toFixed(1)}`).join(' ')
	);
	const areaPath = $derived(
		sorted.length > 1
			? `${linePath} L${xOf(sorted[sorted.length - 1].date).toFixed(1)},${(M.top + innerH).toFixed(1)} L${xOf(sorted[0].date).toFixed(1)},${(M.top + innerH).toFixed(1)} Z`
			: ''
	);

	const dayCount = $derived(Math.max(1, Math.round(span / 86400000) + 1));
	const barW = $derived(Math.max(1, Math.min(16, (innerW / dayCount) * 0.85)));

	function formatDayLabel(day: string): string {
		const d = new Date(`${day}T00:00:00`);
		if (Number.isNaN(d.getTime())) return day;
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	const xTicks = $derived.by(() => {
		if (sorted.length === 0) return [] as { x: number; label: string; anchor: string }[];
		const ticks = [{ x: xOf(sorted[0].date), label: formatDayLabel(sorted[0].date), anchor: 'start' }];
		if (sorted.length > 2) {
			// The middle day only where it clears both ends: the days are not spread evenly.
			const mid = sorted[Math.floor(sorted.length / 2)];
			const midX = xOf(mid.date);
			if (midX - xOf(sorted[0].date) > 72 && xOf(sorted[sorted.length - 1].date) - midX > 72) {
				ticks.push({ x: midX, label: formatDayLabel(mid.date), anchor: 'middle' });
			}
		}
		if (sorted.length > 1) {
			const last = sorted[sorted.length - 1];
			ticks.push({ x: xOf(last.date), label: formatDayLabel(last.date), anchor: 'end' });
		}
		return ticks;
	});
</script>

{#if sorted.length === 0}
	<div class="flex h-32 items-center justify-center text-sm text-ink-muted">No data yet.</div>
{:else}
	<div bind:clientWidth={measured}>
		<svg viewBox="0 0 {W} {H}" width={W} height={H} class="block max-w-full" role="img">
			{#each [0, 0.5, 1] as f (f)}
				{@const y = M.top + innerH - f * innerH}
				<line
					x1={M.left}
					y1={y}
					x2={M.left + innerW}
					y2={y}
					stroke="var(--line-strong)"
					stroke-width="1"
					vector-effect="non-scaling-stroke"
				/>
				<text x={M.left - 6} y={y + 3.5} text-anchor="end" font-size="12" fill="var(--ink-muted)">
					{formatValue(yMax * f)}
				</text>
			{/each}

			{#if kind === 'bar'}
				{#each sorted as p (p.date)}
					<rect
						x={xOf(p.date) - barW / 2}
						y={yOf(p.value)}
						width={barW}
						height={Math.max(0, M.top + innerH - yOf(p.value))}
						fill={color}
					>
						<title>{formatDayLabel(p.date)}: {formatValue(p.value)}</title>
					</rect>
				{/each}
			{:else}
				{#if areaPath}
					<path d={areaPath} fill={color} fill-opacity="0.08" />
				{/if}
				<path d={linePath} fill="none" stroke={color} stroke-width="1.5" vector-effect="non-scaling-stroke" />
				{#each sorted as p (p.date)}
					<circle cx={xOf(p.date)} cy={yOf(p.value)} r="2" fill={color}>
						<title>{formatDayLabel(p.date)}: {formatValue(p.value)}</title>
					</circle>
				{/each}
			{/if}

			{#each xTicks as t (t.x + t.label)}
				<text x={t.x} y={H - 6} text-anchor={t.anchor} font-size="12" fill="var(--ink-muted)">
					{t.label}
				</text>
			{/each}
		</svg>
	</div>
{/if}

<script lang="ts">
	// A time series drawn in SVG on a well, as the design system's charts are
	// (docs/components.md, Data): the series is 1.5px in the primary, the
	// gridlines are `line`, and the labels are HTML at 12px. The plot is a
	// 100 x 100 box stretched over its area, so lines keep their width
	// (non-scaling stroke) and the labels never scale with it. No charting
	// dependency: the frontend builds on the Pi.
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

	// Positions as a share of the plot, 0 to 100.
	function xOf(day: string): number {
		if (sorted.length <= 1) return 50;
		return ((parseDay(day) - t0) / span) * 100;
	}

	function yOf(value: number): number {
		return 100 - (Math.min(value, yMax) / yMax) * 100;
	}

	const linePoints = $derived(sorted.map((p) => `${xOf(p.date).toFixed(2)},${yOf(p.value).toFixed(2)}`));
	const areaPath = $derived(
		sorted.length > 1
			? `M${linePoints.join(' L')} L${xOf(sorted[sorted.length - 1].date).toFixed(2)},100 L${xOf(sorted[0].date).toFixed(2)},100 Z`
			: ''
	);

	const dayCount = $derived(Math.max(1, Math.round(span / 86400000) + 1));
	const barW = $derived(Math.max(0.2, Math.min(3, (100 / dayCount) * 0.85)));

	function formatDayLabel(day: string): string {
		const d = new Date(`${day}T00:00:00`);
		if (Number.isNaN(d.getTime())) return day;
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	const xLabels = $derived.by(() => {
		if (sorted.length === 0) return [] as string[];
		const labels = [formatDayLabel(sorted[0].date)];
		if (sorted.length > 2) labels.push(formatDayLabel(sorted[Math.floor(sorted.length / 2)].date));
		if (sorted.length > 1) labels.push(formatDayLabel(sorted[sorted.length - 1].date));
		return labels;
	});
</script>

{#if sorted.length === 0}
	<div class="flex h-32 items-center justify-center rounded-control bg-well text-sm text-ink-muted">
		No data yet.
	</div>
{:else}
	<div class="rounded-control bg-well px-3 py-4">
		<div class="flex gap-2">
			<div class="num relative h-40 w-11 shrink-0 text-right text-xs text-ink-muted">
				{#each [1, 0.5, 0] as f (f)}
					<span class="absolute right-0 -translate-y-1/2" style:top="{(1 - f) * 100}%">
						{formatValue(yMax * f)}
					</span>
				{/each}
			</div>
			<svg
				viewBox="0 0 100 100"
				preserveAspectRatio="none"
				class="h-40 min-w-0 flex-1 overflow-visible"
				role="img"
				aria-label="{formatDayLabel(sorted[0].date)} to {formatDayLabel(sorted[sorted.length - 1].date)}, up to {formatValue(yMax)}"
			>
				{#each [0, 50, 100] as y (y)}
					<line x1="0" x2="100" y1={y} y2={y} stroke="var(--line)" stroke-width="1" vector-effect="non-scaling-stroke" />
				{/each}

				{#if kind === 'bar'}
					{#each sorted as p (p.date)}
						<rect x={xOf(p.date) - barW / 2} y={yOf(p.value)} width={barW} height={100 - yOf(p.value)} fill={color}>
							<title>{formatDayLabel(p.date)}: {formatValue(p.value)}</title>
						</rect>
					{/each}
				{:else}
					{#if areaPath}<path d={areaPath} fill={color} fill-opacity="0.08" />{/if}
					<polyline
						points={linePoints.join(' ')}
						fill="none"
						stroke={color}
						stroke-width="1.5"
						vector-effect="non-scaling-stroke"
					/>
					<!-- A dot is a line of no length with a round cap, so it stays round when the plot stretches. -->
					{#each sorted as p (p.date)}
						<line
							x1={xOf(p.date)}
							x2={xOf(p.date)}
							y1={yOf(p.value)}
							y2={yOf(p.value)}
							stroke={color}
							stroke-width="4"
							stroke-linecap="round"
							vector-effect="non-scaling-stroke"
						>
							<title>{formatDayLabel(p.date)}: {formatValue(p.value)}</title>
						</line>
					{/each}
				{/if}
			</svg>
		</div>
		<div class="mt-2 ml-[3.25rem] flex justify-between text-xs text-ink-muted">
			{#each xLabels as label, i (i)}<span>{label}</span>{/each}
		</div>
	</div>
{/if}

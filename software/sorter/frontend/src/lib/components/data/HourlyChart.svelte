<!--
	A chart of one number per hour, drawn in SVG on a well as the design system's
	charts are (docs/components.md, Data): tokens for every color, labels in HTML
	at 12px, no chart library (the UI builds on a small ARM board).

	`columns` stacks the series (bottom first) with a 2px gap between segments,
	columns at most 24px wide. `area` is one series: a 1.5px line over a faint
	wash of the same color. Colors follow the series, not its rank, so the
	caller gives each series its token and how much of it shows over the well
	(`opacity`); the legend names every series that has a value.

	Pointing at an hour, or the arrow keys once the chart has focus, show that
	hour's numbers in one tooltip: the total, each series, and the caller's
	`notes`. Nothing is only in the tooltip: "Show as table" lists every hour.
	`flagged` hours (some of what should be sent was dropped) get a mark along
	the bottom, in the warning tone.
-->
<script lang="ts" module>
	export type HourlySeries = {
		key: string;
		label: string;
		// One value per hour; null where the machine did not know it.
		values: (number | null)[];
		// A token (`var(--primary-ink)`), and how much of it shows over the well.
		color: string;
		opacity?: number;
	};

	export type TipRow = { label: string; value: string };
</script>

<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import { formatDayHour, formatHour } from '$lib/sharing/format';

	let {
		label,
		hours,
		series,
		form = 'columns',
		format,
		bytes = false,
		totalLabel = '',
		flagged = [],
		flagLabel = 'Some was dropped',
		notes,
		empty = 'Nothing in this time.'
	}: {
		// The chart's name, for a screen reader and the table.
		label: string;
		// The start of each hour; the last is the current, partial hour.
		hours: number[];
		series: HourlySeries[];
		form?: 'columns' | 'area';
		format: (value: number) => string;
		// The numbers are bytes: the axis tops out at a round number of KB, MB or GB.
		bytes?: boolean;
		// What the number at the top of the tooltip counts ("uploaded").
		totalLabel?: string;
		flagged?: boolean[];
		flagLabel?: string;
		// More numbers about an hour for the tooltip and the table.
		notes?: (hour: number) => TipRow[];
		empty?: string;
	} = $props();

	const H = 160;
	const GAP = 2;
	const MAX_BAR = 24;
	const LINE = 1.5;
	const DOT = 4;

	let plotW = $state(0);
	let hovered = $state<number | null>(null);
	let table = $state(false);

	const n = $derived(hours.length);
	// An hour that is no longer there (the window changed) shows nothing.
	const active = $derived(hovered !== null && hovered < n ? hovered : null);
	const slot = $derived(n > 0 ? plotW / n : 0);
	const barW = $derived(Math.max(1, Math.min(MAX_BAR, slot * 0.7)));

	function valueAt(s: HourlySeries | undefined, i: number): number {
		return s?.values[i] ?? 0;
	}

	// The height of a column: all the series stacked, or the one series.
	const totals = $derived(
		hours.map((_, i) =>
			form === 'area' ? valueAt(series[0], i) : series.reduce((sum, s) => sum + valueAt(s, i), 0)
		)
	);

	// Round the top of the axis up to 1/2/5 x 10^n so its labels read clean; for
	// bytes, in the unit they are written in (1 KB is 1024 bytes).
	function niceMax(value: number): number {
		if (value <= 0) return bytes ? 1024 : 1;
		const unit = bytes ? 1024 ** Math.max(0, Math.floor(Math.log(value) / Math.log(1024))) : 1;
		const scaled = value / unit;
		const pow = Math.pow(10, Math.floor(Math.log10(scaled)));
		for (const step of [1, 2, 5, 10]) if (scaled <= step * pow) return step * pow * unit;
		return 10 * pow * unit;
	}

	const yMax = $derived(niceMax(Math.max(0, ...totals)));
	const isEmpty = $derived(totals.every((total) => total <= 0));

	// Only what has a value shows in the legend; the colors stay with the series.
	const shown = $derived(series.filter((s) => s.values.some((v) => (v ?? 0) > 0)));

	type Segment = { key: string; x: number; y: number; h: number; s: HourlySeries };

	const segments = $derived.by(() => {
		if (form !== 'columns' || slot === 0) return [] as Segment[];
		const out: Segment[] = [];
		for (let i = 0; i < n; i++) {
			let stacked = 0;
			for (const s of series) {
				const v = valueAt(s, i);
				if (v <= 0) continue;
				const h = Math.max(1, (v / yMax) * H);
				// The gap is at the segment's bottom, so the first one sits on the baseline.
				out.push({
					key: `${i}-${s.key}`,
					x: i * slot + (slot - barW) / 2,
					y: H - stacked - h,
					h: Math.max(1, stacked === 0 ? h : h - GAP),
					s
				});
				stacked += h;
			}
		}
		return out;
	});

	const xAt = (i: number) => i * slot + slot / 2;
	const yAt = (v: number) => H - (Math.min(v, yMax) / yMax) * H;

	// The line, broken where an hour is not known, each run with its wash.
	const runs = $derived.by(() => {
		if (form !== 'area' || slot === 0 || !series[0]) return [] as { line: string; wash: string }[];
		const out: { line: string; wash: string }[] = [];
		let points: [number, number][] = [];
		const end = () => {
			if (points.length > 0) {
				const line = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
				const first = points[0][0].toFixed(1);
				const last = points[points.length - 1][0].toFixed(1);
				out.push({ line, wash: `M${line.replaceAll(' ', ' L')} L${last},${H} L${first},${H} Z` });
			}
			points = [];
		};
		for (let i = 0; i < n; i++) {
			const v = series[0].values[i];
			if (v == null) end();
			else points.push([xAt(i), yAt(v)]);
		}
		end();
		return out;
	});

	// The dot on the line: at the hour pointed at, else the latest known.
	const dotAt = $derived.by(() => {
		if (form !== 'area' || !series[0]) return null;
		if (active !== null && series[0].values[active] != null) return active;
		for (let i = n - 1; i >= 0; i--) if (series[0].values[i] != null) return i;
		return null;
	});

	// Hours are named by their time of day, with the day when the window is
	// long or the hour is not today's.
	function at(ts: number): string {
		const sameDay =
			new Date(ts * 1000).toDateString() === new Date(hours[n - 1] * 1000).toDateString();
		return n > 36 || !sameDay ? formatDayHour(ts) : formatHour(ts);
	}

	function when(i: number): string {
		const end = i === n - 1 ? 'now' : formatHour(hours[i] + 3600);
		return `${at(hours[i])} to ${end}`;
	}

	// The first hour, the middle one and now, each under its own column.
	const middle = $derived(Math.floor(n / 2));
	const xLabels = $derived(n === 0 ? [] : [at(hours[0]), at(hours[middle]), 'Now']);

	function rows(i: number): TipRow[] {
		const list =
			form === 'columns'
				? series.flatMap((s) =>
						valueAt(s, i) > 0 ? [{ label: s.label, value: format(valueAt(s, i)) }] : []
					)
				: [];
		return [...list, ...(notes?.(i) ?? [])];
	}

	const tip = $derived(
		active === null
			? null
			: {
					when: when(active),
					total: series[0]?.values[active] == null && form === 'area' ? 'Unknown' : format(totals[active]),
					rows: rows(active)
				}
	);

	function indexAt(event: PointerEvent): number {
		const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
		return Math.min(n - 1, Math.max(0, Math.floor(((event.clientX - box.left) / box.width) * n)));
	}

	function onpointermove(event: PointerEvent) {
		if (n > 0) hovered = indexAt(event);
	}

	function onpointerdown(event: PointerEvent) {
		(event.currentTarget as HTMLElement).focus();
		if (n > 0) hovered = indexAt(event);
	}

	// A mouse leaves the chart; a finger lifts, and the numbers stay until focus goes.
	function onpointerleave(event: PointerEvent) {
		if (event.pointerType === 'mouse') hovered = null;
	}

	function onfocus() {
		if (n > 0) hovered ??= n - 1;
	}

	function onkeydown(event: KeyboardEvent) {
		if (n === 0) return;
		const to: Record<string, number> = {
			ArrowLeft: Math.max(0, (active ?? n) - 1),
			ArrowRight: Math.min(n - 1, (active ?? -1) + 1),
			Home: 0,
			End: n - 1
		};
		if (event.key in to) {
			event.preventDefault();
			hovered = to[event.key];
		} else if (event.key === 'Escape') {
			hovered = null;
		}
	}

	// Left of, over or right of the hour, so the tooltip stays inside the chart.
	const tipStyle = $derived.by(() => {
		if (active === null || plotW === 0) return '';
		const x = xAt(active);
		if (x < plotW * 0.3) return `left:${Math.round(x + 12)}px`;
		if (x > plotW * 0.7) return `right:${Math.round(plotW - x + 12)}px`;
		return `left:${Math.round(x)}px;transform:translateX(-50%)`;
	});
</script>

<div class="rounded-control bg-well px-3 py-3">
	<div class="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
		<ul class="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-muted">
			{#if shown.length > 1}
				{#each shown as s (s.key)}
					<li class="flex items-center gap-1.5">
						<span
							class="size-2.5 shrink-0 rounded-badge"
							style:background-color={s.color}
							style:opacity={s.opacity ?? 1}
						></span>
						{s.label}
					</li>
				{/each}
			{/if}
			{#if flagged.some(Boolean)}
				<li class="flex items-center gap-1.5">
					<span class="h-1 w-2.5 shrink-0 bg-warning-ink"></span>
					{flagLabel}
				</li>
			{/if}
		</ul>
		<Button variant="ghost" size="sm" onclick={() => (table = !table)}>
			{table ? 'Show as chart' : 'Show as table'}
		</Button>
	</div>

	{#if table}
		<div class="max-h-72 overflow-auto rounded-item bg-surface">
			<table class="data-table">
				<caption class="sr-only">{label}</caption>
				<thead>
					<tr>
						<th>Hour</th>
						{#if form === 'columns'}
							{#each series as s (s.key)}<th class="num">{s.label}</th>{/each}
							<th class="num">Total</th>
						{:else}
							<th class="num">{series[0]?.label}</th>
						{/if}
						{#each n > 0 ? (notes?.(0) ?? []) : [] as note (note.label)}
							<th class="num">{note.label}</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each hours as hour, i (hour)}
						<tr>
							<td class="whitespace-nowrap">{when(i)}</td>
							{#if form === 'columns'}
								{#each series as s (s.key)}
									<td class="num whitespace-nowrap">{format(valueAt(s, i))}</td>
								{/each}
							{/if}
							<td class="num whitespace-nowrap">
								{form === 'area' && series[0]?.values[i] == null ? 'Unknown' : format(totals[i])}
							</td>
							{#each notes?.(i) ?? [] as note (note.label)}
								<td class="num whitespace-nowrap">{note.value}</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<div class="flex gap-2">
			<div class="num relative w-14 shrink-0 text-right text-xs text-ink-muted" style:height="{H}px">
				{#each [1, 0.5, 0] as f (f)}
					<span class="absolute right-0 -translate-y-1/2" style:top="{(1 - f) * 100}%">
						{format(yMax * f)}
					</span>
				{/each}
			</div>
			<div class="min-w-0 flex-1">
				<div class="relative" style:height="{H}px" bind:clientWidth={plotW}>
					<svg
						width={plotW}
						height={H}
						viewBox="0 0 {plotW} {H}"
						class="block overflow-visible"
						aria-hidden="true"
					>
						{#if active !== null}
							<rect x={active * slot} y="0" width={slot} height={H} fill="var(--hover)" />
						{/if}
						{#each [0, H / 2] as y (y)}
							<line
								x1="0"
								x2={plotW}
								y1={y + 0.5}
								y2={y + 0.5}
								stroke="var(--line)"
								stroke-width="1"
								shape-rendering="crispEdges"
							/>
						{/each}
						<line
							x1="0"
							x2={plotW}
							y1={H - 0.5}
							y2={H - 0.5}
							stroke="var(--line-strong)"
							stroke-width="1"
							shape-rendering="crispEdges"
						/>

						{#if form === 'columns'}
							{#each segments as seg (seg.key)}
								<rect
									x={seg.x}
									y={seg.y}
									width={barW}
									height={seg.h}
									fill={seg.s.color}
									fill-opacity={seg.s.opacity ?? 1}
								/>
							{/each}
						{:else if series[0]}
							{#each runs as run, r (r)}
								<path d={run.wash} fill={series[0].color} fill-opacity="0.1" />
								<polyline
									points={run.line}
									fill="none"
									stroke={series[0].color}
									stroke-width={LINE}
									stroke-linejoin="round"
									stroke-linecap="round"
								/>
							{/each}
							{#if active !== null}
								<line
									x1={xAt(active)}
									x2={xAt(active)}
									y1="0"
									y2={H}
									stroke="var(--line-strong)"
									stroke-width="1"
									shape-rendering="crispEdges"
								/>
							{/if}
							{#if dotAt !== null}
								<!-- A dot with a 2px ring in the well's color, so it stays clear of the line. -->
								<circle
									cx={xAt(dotAt)}
									cy={yAt(series[0].values[dotAt] ?? 0)}
									r={DOT}
									fill={series[0].color}
									stroke="var(--well)"
									stroke-width="2"
								/>
							{/if}
						{/if}

						{#each flagged as isFlagged, i (i)}
							{#if isFlagged && slot > 0}
								<rect
									x={i * slot + 0.5}
									y={H - 4}
									width={Math.max(1, slot - 1)}
									height="4"
									fill="var(--warning-ink)"
								/>
							{/if}
						{/each}
					</svg>

					{#if isEmpty}
						<p
							class="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-ink-muted"
						>
							{empty}
						</p>
					{/if}

					<!-- The chart's one tab stop: the arrow keys read it hour by hour. -->
					<button
						type="button"
						aria-label="{label}. Use the arrow keys to read each hour."
						class="absolute inset-0 cursor-default"
						{onpointermove}
						{onpointerdown}
						{onpointerleave}
						{onfocus}
						{onkeydown}
						onblur={() => (hovered = null)}
					></button>

					{#if tip}
						<div
							class="pointer-events-none absolute top-1 z-10 min-w-44 rounded-control border border-line bg-raised px-3 py-2 text-sm whitespace-nowrap"
							style={tipStyle}
						>
							<div class="text-xs text-ink-muted">{tip.when}</div>
							<div class="num mt-0.5 font-semibold text-ink">
								{tip.total}{#if totalLabel}{' '}<span class="font-normal text-ink-muted"
										>{totalLabel}</span
									>{/if}
							</div>
							{#each tip.rows as row (row.label)}
								<div class="mt-0.5 flex items-baseline justify-between gap-4">
									<span class="text-ink-muted">{row.label}</span>
									<span class="num font-medium text-ink">{row.value}</span>
								</div>
							{/each}
						</div>
					{/if}
					<span class="sr-only" aria-live="polite">
						{#if tip}{tip.when}: {tip.total}{#each tip.rows as row (row.label)}, {row.label} {row.value}{/each}{/if}
					</span>
				</div>
				<div class="relative mt-2 h-4 text-xs whitespace-nowrap text-ink-muted">
					{#if xLabels.length > 0}
						<span class="absolute left-0">{xLabels[0]}</span>
						<span class="absolute -translate-x-1/2" style:left="{xAt(middle)}px">{xLabels[1]}</span>
						<span class="absolute right-0">{xLabels[2]}</span>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

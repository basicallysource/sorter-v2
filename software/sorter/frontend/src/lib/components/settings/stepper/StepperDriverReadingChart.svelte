<!--
	One thing a motor's driver reports, drawn over time: its name, the newest
	reading with its unit, a sentence saying what it shows and what a bad reading
	looks like, and a small graph. Drawn in SVG as the design system's charts are
	(docs/components.md, Data): the series is 1.5px in the primary, gridlines are
	`line`, labels are HTML at 12px. The parent puts several on one well, over
	one time axis and one pointer: pointing at any graph marks the same moment on
	all of them, and each then says its reading at that moment.

	The line breaks where a reading has no number (`read` gives null) and across
	a gap in the record. A reading with none beside it is a dot.
-->
<script lang="ts">
	import type { DriverSample } from '$lib/api/drivers';

	let {
		title,
		caption,
		period,
		samples,
		read,
		from,
		to,
		breakAfter,
		max = null,
		least = 1,
		ticks = undefined,
		format,
		none = 'No reading',
		refs = [],
		cursor,
		onhover
	}: {
		title: string;
		// What the graph shows and what a bad reading looks like.
		caption: string;
		// The time drawn, in words, for the graph's accessible name: "the last 10 minutes".
		period: string;
		// Every reading in the time drawn, oldest first.
		samples: DriverSample[];
		// This graph's number in a reading; null where it has none.
		read: (sample: DriverSample) => number | null;
		// The time drawn, in seconds since the epoch.
		from: number;
		to: number;
		// Two readings further apart than this many seconds have a gap in the record between them.
		breakAfter: number;
		// The top of the scale. Null fits the scale to the readings, never under `least`.
		max?: number | null;
		least?: number;
		// The levels that get a gridline and a label: the top, the middle and the
		// bottom of the scale when left out.
		ticks?: number[];
		// A reading with its unit.
		format: (value: number) => string;
		// What stands where a reading has no number.
		none?: string;
		// Settings the reading is read against, drawn as lines across the graph.
		refs?: { value: number; label: string; dotted?: boolean }[];
		// The reading under the pointer, whichever graph the pointer is on.
		cursor: DriverSample | null;
		// Where the pointer is across this graph, 0 to 1, or null when it leaves.
		onhover: (share: number | null) => void;
	} = $props();

	function numberIn(sample: DriverSample): number | null {
		const value = read(sample);
		return typeof value === 'number' && Number.isFinite(value) ? value : null;
	}

	// A fitted scale ends on 1, 2 or 5 times a power of ten, so its labels read clean.
	function roundedUp(value: number): number {
		if (!(value > 0)) return 1;
		const power = Math.pow(10, Math.floor(Math.log10(value)));
		for (const step of [1, 2, 5]) {
			if (value <= step * power) return step * power;
		}
		return 10 * power;
	}

	const scale = $derived.by(() => {
		if (max !== null) return { lo: 0, hi: max };
		let lo = 0;
		let hi = 0;
		for (const sample of samples) {
			const value = numberIn(sample);
			if (value === null) continue;
			if (value < lo) lo = value;
			if (value > hi) hi = value;
		}
		return {
			lo: lo < 0 ? -roundedUp(Math.max(-lo, least)) : 0,
			hi: roundedUp(Math.max(hi, least))
		};
	});
	const levels = $derived(ticks ?? [scale.hi, (scale.hi + scale.lo) / 2, scale.lo]);
	const span = $derived(Math.max(1, to - from));

	// Positions as a share of the plot, 0 to 100.
	function x(t: number): number {
		return ((t - from) / span) * 100;
	}
	function y(value: number): number {
		const { lo, hi } = scale;
		return 100 - ((Math.min(Math.max(value, lo), hi) - lo) / (hi - lo)) * 100;
	}

	// Two paths however many pieces the line is in: the runs of readings, and
	// the lone ones as lines of no length, which a round cap draws as dots.
	const drawn = $derived.by(() => {
		let line = '';
		let dots = '';
		let run: string[] = [];
		let lastT = 0;
		const close = () => {
			if (run.length === 1) dots += `M${run[0]}L${run[0]}`;
			else if (run.length > 1) line += `M${run.join('L')}`;
			run = [];
		};
		for (const sample of samples) {
			const value = numberIn(sample);
			if (value === null || sample.t < from || sample.t > to) {
				close();
				continue;
			}
			if (run.length > 0 && sample.t - lastT > breakAfter) close();
			run.push(`${x(sample.t).toFixed(2)},${y(value).toFixed(2)}`);
			lastT = sample.t;
		}
		close();
		return { line, dots };
	});

	function say(sample: DriverSample | null): string {
		const value = sample ? numberIn(sample) : null;
		return value === null ? none : format(value);
	}

	const newest = $derived(samples.length > 0 ? samples[samples.length - 1] : null);
	const readout = $derived(say(cursor ?? newest));
	const cursorX = $derived(cursor && cursor.t >= from && cursor.t <= to ? x(cursor.t) : null);
	const cursorValue = $derived(cursor ? numberIn(cursor) : null);

	function point(event: PointerEvent) {
		const box = (event.currentTarget as SVGElement).getBoundingClientRect();
		if (box.width <= 0) return;
		onhover(Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)));
	}
</script>

<div>
	<div class="flex items-baseline justify-between gap-4">
		<h4 class="text-sm font-medium text-ink">{title}</h4>
		<p class="num min-w-0 truncate text-sm text-ink">{readout}</p>
	</div>
	<p class="mt-0.5 max-w-prose text-sm text-ink-muted">{caption}</p>
	<div class="mt-3 flex gap-2">
		<div class="num relative h-20 w-12 shrink-0 text-right text-xs text-ink-muted">
			{#each levels as level (level)}
				<span class="absolute right-0 -translate-y-1/2" style:top="{y(level)}%">
					{level.toLocaleString()}
				</span>
			{/each}
		</div>
		<svg
			viewBox="0 0 100 100"
			preserveAspectRatio="none"
			class="h-20 min-w-0 flex-1 cursor-crosshair overflow-visible"
			role="img"
			aria-label="{title} over {period}. Newest reading: {say(newest)}. Point at it for a moment's reading."
			onpointermove={point}
			onpointerdown={point}
			onpointerleave={() => onhover(null)}
		>
			{#each levels as level (level)}
				<line
					x1="0"
					x2="100"
					y1={y(level)}
					y2={y(level)}
					stroke="var(--line)"
					stroke-width="1"
					vector-effect="non-scaling-stroke"
				/>
			{/each}
			{#each refs as ref (ref.label)}
				<line
					x1="0"
					x2="100"
					y1={y(ref.value)}
					y2={y(ref.value)}
					stroke="var(--ink-muted)"
					stroke-width="1"
					stroke-dasharray={ref.dotted ? '1.5 3' : '5 3'}
					vector-effect="non-scaling-stroke"
				/>
			{/each}
			{#if drawn.line}
				<path
					d={drawn.line}
					fill="none"
					stroke="var(--primary)"
					stroke-width="1.5"
					vector-effect="non-scaling-stroke"
				/>
			{/if}
			{#if drawn.dots}
				<path
					d={drawn.dots}
					fill="none"
					stroke="var(--primary)"
					stroke-width="3"
					stroke-linecap="round"
					vector-effect="non-scaling-stroke"
				/>
			{/if}
			{#if cursorX !== null}
				<line
					x1={cursorX}
					x2={cursorX}
					y1="0"
					y2="100"
					stroke="var(--ink-muted)"
					stroke-width="1"
					stroke-dasharray="3 3"
					vector-effect="non-scaling-stroke"
				/>
				{#if cursorValue !== null}
					<line
						x1={cursorX}
						x2={cursorX}
						y1={y(cursorValue)}
						y2={y(cursorValue)}
						stroke="var(--primary)"
						stroke-width="6"
						stroke-linecap="round"
						vector-effect="non-scaling-stroke"
					/>
				{/if}
			{/if}
		</svg>
	</div>
	{#if refs.length > 0}
		<div class="mt-2 ml-14 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
			{#each refs as ref (ref.label)}
				<span class="flex items-center gap-1.5">
					<span
						class="h-0 w-4 border-t border-ink-muted {ref.dotted
							? 'border-dotted'
							: 'border-dashed'}"
					></span>
					{ref.label}
				</span>
			{/each}
		</div>
	{/if}
</div>

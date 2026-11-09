<!--
	The computer's hottest sensor over the last hours, one point a minute, drawn
	in SVG on a well as the design system's charts are (docs/components.md,
	Data): the series is 1.5px in the primary, gridlines are `line`, labels are
	HTML at 12px muted. The minutes when the kernel was slowing the chip down
	are shaded in the warning tint, and the limits from the chip's own trip
	points are dashed lines in their status colors: warning where it starts
	slowing down, danger where it is too hot. A gap of more than two minutes
	(the backend was not running) breaks the line.
-->
<script lang="ts" module>
	export type HealthPoint = { t: number; temp_c: number | null; slowed: number | null };
</script>

<script lang="ts">
	let {
		points,
		from,
		to,
		hotC = null,
		slowsC = null
	}: {
		points: HealthPoint[];
		// The span drawn, in seconds since the epoch.
		from: number;
		to: number;
		hotC?: number | null;
		slowsC?: number | null;
	} = $props();

	const temps = $derived(points.filter((p) => p.temp_c != null).map((p) => p.temp_c as number));
	const yMin = $derived(Math.floor(Math.min(30, ...temps) / 10) * 10);
	const yMax = $derived(Math.ceil(Math.max(hotC != null ? hotC + 5 : 60, ...temps) / 10) * 10);
	const span = $derived(Math.max(60, to - from));

	function x(t: number): number {
		return ((t - from) / span) * 100;
	}
	function y(c: number): number {
		return 100 - ((Math.min(Math.max(c, yMin), yMax) - yMin) / (yMax - yMin)) * 100;
	}

	// The line, cut where minutes are missing.
	const segments = $derived.by(() => {
		const out: string[][] = [];
		let last: number | null = null;
		for (const p of points) {
			if (p.temp_c == null || p.t < from) continue;
			if (last == null || p.t - last > 120) out.push([]);
			out[out.length - 1].push(`${x(p.t + 30).toFixed(2)},${y(p.temp_c).toFixed(2)}`);
			last = p.t;
		}
		return out;
	});
	const minuteW = $derived((60 / span) * 100);
	const slowedMinutes = $derived(points.filter((p) => (p.slowed ?? 0) > 0 && p.t >= from));

	function clock(t: number): string {
		return new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true });
	}
	const ticks = $derived([yMax, (yMax + yMin) / 2, yMin]);
</script>

{#if temps.length === 0}
	<div class="flex h-32 items-center justify-center rounded-control bg-well text-sm text-ink-muted">
		No temperatures yet.
	</div>
{:else}
	<div class="rounded-control bg-well px-3 py-4">
		<div class="flex gap-2">
			<div class="num relative h-40 w-11 shrink-0 text-right text-xs text-ink-muted">
				{#each ticks as c (c)}
					<span class="absolute right-0 -translate-y-1/2" style:top="{y(c)}%">{c} °C</span>
				{/each}
			</div>
			<svg
				viewBox="0 0 100 100"
				preserveAspectRatio="none"
				class="h-40 min-w-0 flex-1 overflow-visible"
				role="img"
				aria-label="Hottest temperature from {clock(from)} to {clock(to)}, at most {Math.max(...temps)} °C"
			>
				{#each slowedMinutes as p (p.t)}
					<rect x={x(p.t)} y="0" width={minuteW} height="100" fill="var(--warning-soft)">
						<title>{clock(p.t)}: slowed down in {Math.round((p.slowed ?? 0) * 100)}% of the readings</title>
					</rect>
				{/each}
				{#each ticks as c (c)}
					<line x1="0" x2="100" y1={y(c)} y2={y(c)} stroke="var(--line)" stroke-width="1" vector-effect="non-scaling-stroke" />
				{/each}
				{#if slowsC != null}
					<line x1="0" x2="100" y1={y(slowsC)} y2={y(slowsC)} stroke="var(--warning)" stroke-width="1" stroke-dasharray="4 3" vector-effect="non-scaling-stroke" />
				{/if}
				{#if hotC != null}
					<line x1="0" x2="100" y1={y(hotC)} y2={y(hotC)} stroke="var(--danger)" stroke-width="1" stroke-dasharray="4 3" vector-effect="non-scaling-stroke" />
				{/if}
				{#each segments as segment, i (i)}
					{#if segment.length === 1}
						<!-- A lone minute is a line of no length with a round cap, so it stays round. -->
						{@const [px, py] = segment[0].split(',')}
						<line x1={px} x2={px} y1={py} y2={py} stroke="var(--primary)" stroke-width="4" stroke-linecap="round" vector-effect="non-scaling-stroke" />
					{:else}
						<polyline points={segment.join(' ')} fill="none" stroke="var(--primary)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
					{/if}
				{/each}
			</svg>
		</div>
		<div class="mt-2 ml-[3.25rem] flex justify-between text-xs text-ink-muted">
			<span>{clock(from)}</span><span>{clock((from + to) / 2)}</span><span>{clock(to)}</span>
		</div>
		<div class="mt-3 ml-[3.25rem] flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
			<span class="flex items-center gap-1.5"><span class="h-0.5 w-4 bg-primary"></span>Hottest sensor</span>
			{#if slowsC != null}
				<span class="flex items-center gap-1.5"><span class="h-0 w-4 border-t border-dashed border-warning"></span>Starts slowing down, {slowsC} °C</span>
			{/if}
			{#if hotC != null}
				<span class="flex items-center gap-1.5"><span class="h-0 w-4 border-t border-dashed border-danger"></span>Too hot, {hotC} °C</span>
			{/if}
			<span class="flex items-center gap-1.5"><span class="h-2.5 w-3 bg-warning-soft"></span>Slowed down</span>
		</div>
	</div>
{/if}

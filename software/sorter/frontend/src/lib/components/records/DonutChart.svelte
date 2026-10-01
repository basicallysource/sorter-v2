<script lang="ts">
	// A donut drawn in SVG on a well. Segments are stroke-dasharray on a circle,
	// so there is no arc math to get wrong; the legend carries the exact numbers.
	export type DonutSegment = { label: string; value: number; color: string };

	let {
		segments,
		centerLabel = ''
	}: {
		segments: DonutSegment[];
		centerLabel?: string;
	} = $props();

	const R = 42;
	const STROKE = 20;
	const C = 2 * Math.PI * R;

	const total = $derived(segments.reduce((sum, s) => sum + s.value, 0));
	const arcs = $derived.by(() => {
		let offset = 0;
		return segments
			.filter((s) => s.value > 0)
			.map((s) => {
				const frac = total > 0 ? s.value / total : 0;
				const arc = { ...s, frac, dash: frac * C, offset };
				offset += frac * C;
				return arc;
			});
	});

	function pct(frac: number): string {
		return `${(frac * 100).toFixed(frac >= 0.1 ? 0 : 1)}%`;
	}
</script>

{#if total === 0}
	<div class="flex h-32 items-center justify-center rounded-control bg-well text-sm text-ink-muted">
		No data yet.
	</div>
{:else}
	<div class="flex flex-wrap items-center gap-4 rounded-control bg-well p-4">
		<div class="relative size-36 shrink-0">
			<svg viewBox="0 0 120 120" class="size-full" role="img" aria-label="{centerLabel || 'Total'}: {total.toLocaleString()}">
				<circle cx="60" cy="60" r={R} fill="none" stroke="var(--line)" stroke-width={STROKE} />
				{#each arcs as a (a.label)}
					<circle
						cx="60"
						cy="60"
						r={R}
						fill="none"
						stroke={a.color}
						stroke-width={STROKE}
						stroke-dasharray="{a.dash} {C - a.dash}"
						stroke-dashoffset={-a.offset}
						transform="rotate(-90 60 60)"
					>
						<title>{a.label}: {a.value.toLocaleString()} ({pct(a.frac)})</title>
					</circle>
				{/each}
			</svg>
			<div class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
				<span class="num text-base font-semibold text-ink">{total.toLocaleString()}</span>
				{#if centerLabel}<span class="text-xs text-ink-muted">{centerLabel}</span>{/if}
			</div>
		</div>
		<ul class="flex min-w-0 flex-1 flex-col gap-1">
			{#each arcs as a (a.label)}
				<li class="flex items-center gap-2 text-sm">
					<span class="size-3 shrink-0 rounded-badge" style:background-color={a.color}></span>
					<span class="truncate text-ink">{a.label}</span>
					<span class="num ml-auto text-ink-muted">{a.value.toLocaleString()} · {pct(a.frac)}</span>
				</li>
			{/each}
		</ul>
	</div>
{/if}

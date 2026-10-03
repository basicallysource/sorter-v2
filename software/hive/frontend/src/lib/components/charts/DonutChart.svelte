<script lang="ts">
	// A donut as SVG: segments are stroke-dasharray on one circle, so there is
	// no arc math; the legend carries the exact numbers.
	// `key` must be unique — labels are not (two machines can share a name).
	export type DonutSegment = { key: string; label: string; value: number; color: string };

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
	<div class="flex h-32 items-center justify-center text-sm text-ink-muted">No data yet.</div>
{:else}
	<div class="flex flex-wrap items-center gap-4">
		<svg viewBox="0 0 120 120" class="size-36 shrink-0" role="img">
			<circle cx="60" cy="60" r={R} fill="none" stroke="var(--track)" stroke-width={STROKE} />
			{#each arcs as a (a.key)}
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
			<text x="60" y="58" text-anchor="middle" font-size="14" font-weight="600" fill="var(--ink)">
				{total.toLocaleString()}
			</text>
			{#if centerLabel}
				<text x="60" y="73" text-anchor="middle" font-size="10" fill="var(--ink-muted)">
					{centerLabel}
				</text>
			{/if}
		</svg>
		<div class="flex min-w-0 flex-1 flex-col gap-1">
			{#each arcs as a (a.key)}
				<div class="flex items-center gap-2 text-sm">
					<span class="size-3 shrink-0 rounded-badge" style:background-color={a.color}></span>
					<span class="truncate text-ink">{a.label}</span>
					<span class="num ml-auto text-ink-muted">
						{a.value.toLocaleString()}, {pct(a.frac)}
					</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

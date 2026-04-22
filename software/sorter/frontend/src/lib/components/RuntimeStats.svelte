<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { LayoutDashboard } from 'lucide-svelte';

	const ctx = getMachineContext();

	type ChannelThroughputEntry = {
		exit_count?: number;
		overall_ppm?: number;
		active_ppm?: number;
		outcomes?: Record<string, { count?: number; active_ppm?: number }>;
	};

	const runtime_stats = $derived((ctx.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const counts = $derived((runtime_stats.counts ?? {}) as Record<string, number>);
	const throughput = $derived((runtime_stats.throughput ?? {}) as Record<string, unknown>);
	const channel_throughput = $derived(
		(runtime_stats.channel_throughput ?? {}) as Record<string, ChannelThroughputEntry>
	);
	const c4 = $derived(channel_throughput.classification_channel ?? {});
	const state_machines = $derived(
		(runtime_stats.state_machines ?? {}) as Record<
			string,
			{ current_state?: string }
		>
	);

	// Derived metrics
	const pieces_seen = $derived(counts.pieces_seen ?? 0);
	const classified_n = $derived(counts.classified ?? 0);
	const distributed_n = $derived(counts.distributed ?? 0);
	const multi_drop_n = $derived(counts.multi_drop_fail ?? 0);
	const unknown_n = $derived((counts.unknown ?? 0) + (counts.not_found ?? 0));

	// Distribution rate (target 10/min). Prefer the C4 classification channel's
	// active_ppm for a "current rate" signal; fall back to overall.
	const dist_rate_ppm = $derived.by(() => {
		const outcomes = c4.outcomes ?? {};
		const classified = outcomes.classified?.active_ppm;
		if (typeof classified === 'number' && classified > 0) return classified;
		const overall = throughput.overall_ppm;
		return typeof overall === 'number' ? overall : 0;
	});

	// Classification success rate (classified vs. total finished classifications).
	const classification_success_pct = $derived.by(() => {
		const finished = classified_n + unknown_n + multi_drop_n;
		if (finished === 0) return null;
		return (classified_n / finished) * 100;
	});

	// Multi-drop rate: multi_drop_fail / pieces_seen.
	const multi_drop_pct = $derived.by(() => {
		if (pieces_seen === 0) return null;
		return (multi_drop_n / pieces_seen) * 100;
	});

	const c4_active_ppm = $derived(typeof c4.active_ppm === 'number' ? c4.active_ppm : 0);

	// Feed rate: pieces_seen / running_time_s.
	const feed_rate_ppm = $derived.by(() => {
		const running_s = throughput.running_time_s;
		if (typeof running_s !== 'number' || running_s <= 0) return 0;
		return (pieces_seen * 60) / running_s;
	});

	// Active pieces in C4 (pieces past feeding, pre-distributed).
	const active_in_c4 = $derived.by(() => {
		const recent = ctx.machine?.recentObjects ?? [];
		return recent.filter(
			(o) =>
				o.first_carousel_seen_ts != null &&
				o.stage !== 'distributed' &&
				!o.distributed_at
		).length;
	});

	// ── Local rolling 60 s sparkline ────────────────────────────────────────
	// We track classified_n over time locally so we can show the last 60 s of
	// classification throughput in 10 s buckets (6 bars).
	const BUCKET_S = 10;
	const N_BUCKETS = 6;
	let samples = $state<{ t: number; classified: number }[]>([]);
	let now_tick = $state(0);
	$effect(() => {
		const id = setInterval(() => {
			now_tick += 1;
			const now = Date.now() / 1000;
			samples = [
				...samples.filter((s) => now - s.t <= BUCKET_S * N_BUCKETS + BUCKET_S),
				{ t: now, classified: classified_n }
			];
		}, 1000);
		return () => clearInterval(id);
	});

	const buckets = $derived.by(() => {
		void now_tick;
		const now = Date.now() / 1000;
		const out: number[] = new Array(N_BUCKETS).fill(0);
		for (let i = 0; i < N_BUCKETS; i += 1) {
			const lo = now - BUCKET_S * (N_BUCKETS - i);
			const hi = now - BUCKET_S * (N_BUCKETS - i - 1);
			const earliest = samples.find((s) => s.t >= lo);
			const latest = [...samples].reverse().find((s) => s.t <= hi);
			if (earliest && latest && latest.classified >= earliest.classified) {
				out[i] = latest.classified - earliest.classified;
			}
		}
		return out;
	});

	const peak_bucket = $derived(Math.max(1, ...buckets));

	function fmtInt(n: number): string {
		return Number.isFinite(n) ? Math.round(n).toString() : '–';
	}

	function fmtPct(n: number | null, digits = 0): string {
		if (n == null || !Number.isFinite(n)) return '–';
		return `${n.toFixed(digits)}%`;
	}

	function fmtPpm(n: number | null | undefined): string {
		if (typeof n !== 'number' || !Number.isFinite(n)) return '–';
		return n.toFixed(1);
	}
</script>

<div class="flex h-full flex-col">
	<div class="flex-1 overflow-y-auto p-2">
		{#if !ctx.machine || !ctx.machine.runtimeStats}
			<div class="text-sm text-text-muted">No runtime stats yet</div>
		{:else}
			<!-- Primary tile: distribution rate (neutral, no target indicator) -->
			<div class="grid grid-cols-2 gap-2">
				<div class="border border-border bg-bg p-2">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						Distributed / min
					</div>
					<div class="flex items-baseline gap-1">
						<span class="text-3xl font-semibold tabular-nums text-text">
							{fmtPpm(dist_rate_ppm)}
						</span>
						<span class="text-xs text-text-muted">ppm</span>
					</div>
				</div>
				<div class="border border-border bg-bg p-2">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						Classify success
					</div>
					<div class="flex items-baseline gap-1">
						<span class="text-3xl font-semibold tabular-nums text-text">
							{fmtPct(classification_success_pct)}
						</span>
						<span class="text-xs text-text-muted tabular-nums">
							{classified_n}/{classified_n + unknown_n + multi_drop_n}
						</span>
					</div>
				</div>

				<div class="border border-border bg-bg p-2">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						Multi-drop rate
					</div>
					<div class="flex items-baseline gap-1">
						<span class="text-2xl font-semibold tabular-nums text-text">
							{fmtPct(multi_drop_pct, 1)}
						</span>
						<span class="text-xs text-text-muted tabular-nums">
							{multi_drop_n}/{pieces_seen}
						</span>
					</div>
				</div>
				<div class="border border-border bg-bg p-2">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						Feed rate
					</div>
					<div class="flex items-baseline gap-1">
						<span class="text-2xl font-semibold tabular-nums text-text">
							{fmtPpm(feed_rate_ppm)}
						</span>
						<span class="text-xs text-text-muted">ppm seen</span>
					</div>
				</div>

				<div class="border border-border bg-bg p-2">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						C4 active ppm
					</div>
					<div class="flex items-baseline gap-1">
						<span class="text-2xl font-semibold tabular-nums text-text">
							{fmtPpm(c4_active_ppm)}
						</span>
					</div>
				</div>
				<div class="border border-border bg-bg p-2">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						In C4
					</div>
					<div class="flex items-baseline gap-1">
						<span class="text-2xl font-semibold tabular-nums text-text">
							{fmtInt(active_in_c4)}
						</span>
						<span class="text-xs text-text-muted">pieces</span>
					</div>
				</div>
			</div>

			<!-- 60 s sparkline of classifications in 10 s buckets -->
			<div class="mt-2 border border-border bg-bg p-2">
				<div class="flex items-baseline justify-between">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						Last 60 s classifications
					</div>
					<div class="text-xs text-text-muted tabular-nums">
						peak {peak_bucket}
					</div>
				</div>
				<div class="mt-1 flex h-10 items-end gap-0.5">
					{#each buckets as v, i (i)}
						<div
							class="flex-1 bg-primary/80"
							style="height: {peak_bucket > 0 ? (v / peak_bucket) * 100 : 0}%; min-height: 1px;"
							title="{v} classified ({(N_BUCKETS - i) * BUCKET_S}s ago)"
						></div>
					{/each}
				</div>
			</div>

			<!-- Totals footer strip -->
			<div class="mt-2 flex items-baseline justify-between border border-border bg-bg px-2 py-1.5 text-sm">
				<span class="text-text-muted">Totals</span>
				<div class="flex items-baseline gap-3 tabular-nums">
					<span class="text-text-muted">seen <span class="text-text">{fmtInt(pieces_seen)}</span></span>
					<span class="text-text-muted">cls <span class="text-text">{fmtInt(classified_n)}</span></span>
					<span class="text-text-muted">dist <span class="text-text">{fmtInt(distributed_n)}</span></span>
				</div>
			</div>
		{/if}
	</div>
</div>

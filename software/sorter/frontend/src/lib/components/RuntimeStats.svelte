<script lang="ts">
	import Stat from '$lib/components/ui/Stat.svelte';
	import { getMachineContext } from '$lib/machines/context';

	const ctx = getMachineContext();

	type ChannelThroughputEntry = {
		active_ppm?: number;
	};

	const runtime_stats = $derived((ctx.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const counts = $derived((runtime_stats.counts ?? {}) as Record<string, number>);
	const throughput = $derived((runtime_stats.throughput ?? {}) as Record<string, unknown>);
	const channel_throughput = $derived(
		(runtime_stats.channel_throughput ?? {}) as Record<string, ChannelThroughputEntry>
	);
	const c4 = $derived(channel_throughput.classification_channel ?? {});

	// Derived metrics
	const pieces_seen = $derived(counts.pieces_seen ?? 0);
	const classified_n = $derived(counts.classified ?? 0);
	const distributed_n = $derived(counts.distributed ?? 0);
	const multi_drop_n = $derived(counts.multi_drop_fail ?? 0);
	const unknown_n = $derived((counts.unknown ?? 0) + (counts.not_found ?? 0));

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

	// Rolling 5-minute distributed ppm — all pieces physically distributed in
	// the last 300 s, regardless of classification outcome.
	const rolling_5min_ppm = $derived.by(() => {
		const v = (throughput as Record<string, unknown>).rolling_5min_ppm;
		return typeof v === 'number' && Number.isFinite(v) ? v : null;
	});

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

<div class="h-full overflow-y-auto">
	{#if !ctx.machine || !ctx.machine.runtimeStats}
		<p class="px-4 py-8 text-center text-sm text-ink-muted">No runtime stats yet</p>
	{:else}
		<div class="grid grid-cols-2 gap-px bg-line">
			<div class="bg-surface">
				<Stat
					label="Distributed a minute"
					value={fmtPpm(rolling_5min_ppm)}
					unit="ppm"
					hint="5 min average, goal 8"
				/>
			</div>
			<div class="bg-surface">
				<Stat
					label="Classified"
					value={fmtPct(classification_success_pct)}
					hint="{classified_n} of {classified_n + unknown_n + multi_drop_n}"
				/>
			</div>
			<div class="bg-surface">
				<Stat
					label="Multi-drop rate"
					value={fmtPct(multi_drop_pct, 1)}
					hint="{multi_drop_n} of {pieces_seen}"
				/>
			</div>
			<div class="bg-surface">
				<Stat label="Feed rate" value={fmtPpm(feed_rate_ppm)} unit="ppm" hint="Pieces seen" />
			</div>
			<div class="bg-surface">
				<Stat label="C4 active" value={fmtPpm(c4_active_ppm)} unit="ppm" />
			</div>
			<div class="bg-surface">
				<Stat label="On C4" value={fmtInt(active_in_c4)} unit="pieces" />
			</div>
		</div>

		<!-- 60 s of classifications in 10 s buckets -->
		<div class="border-t border-line px-4 py-3">
			<div class="flex items-baseline justify-between gap-3">
				<span class="label">Classified in the last 60 s</span>
				<span class="num text-sm text-ink-muted">Peak {peak_bucket}</span>
			</div>
			<div class="mt-2 flex h-10 items-end gap-0.5">
				{#each buckets as v, i (i)}
					<div
						class="min-h-px flex-1 bg-primary"
						style:height="{peak_bucket > 0 ? (v / peak_bucket) * 100 : 0}%"
						title="{v} classified ({(N_BUCKETS - i) * BUCKET_S} s ago)"
					></div>
				{/each}
			</div>
		</div>

		<div class="flex items-baseline justify-between gap-3 border-t border-line px-4 py-2.5 text-sm">
			<span class="text-ink-muted">Totals</span>
			<span class="num flex items-baseline gap-3 text-ink-muted">
				<span>Seen <span class="text-ink">{fmtInt(pieces_seen)}</span></span>
				<span>Classified <span class="text-ink">{fmtInt(classified_n)}</span></span>
				<span>Distributed <span class="text-ink">{fmtInt(distributed_n)}</span></span>
			</span>
		</div>
	{/if}
</div>

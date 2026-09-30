<script lang="ts">
	/*
		How sorting is going: the rates that matter (pieces classified and fed a
		minute, the share that were multi-drops) and a graph of them over time.
		Everything comes from the machine's piece records (/runtime-stats/rates),
		so it survives restarts and a tab left in the background.
	*/
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';

	type Bucket = { t: number; seen: number; classified: number; multi_drop: number };
	type Span = '10m' | '1h' | 'today';

	const ctx = getMachineContext();
	const SPANS: { value: Span; label: string }[] = [
		{ value: '10m', label: '10 min' },
		{ value: '1h', label: '1 hour' },
		{ value: 'today', label: 'Today' }
	];
	// Rates on the numbers are over the last five minutes.
	const RECENT_S = 300;

	let span = $state<Span>('1h');
	let buckets = $state<Bucket[]>([]);
	let window_ = $state({ since: 0, bucket: 60, now: 0 });

	function windowFor(s: Span): { since: number; bucket: number } {
		const now = Date.now() / 1000;
		if (s === '10m') return { since: now - 600, bucket: 20 };
		if (s === '1h') return { since: now - 3600, bucket: 60 };
		const midnight = new Date();
		midnight.setHours(0, 0, 0, 0);
		return { since: midnight.getTime() / 1000, bucket: 300 };
	}

	async function load() {
		const w = windowFor(span);
		const base = machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
		try {
			const res = await fetch(`${base}/runtime-stats/rates?since=${w.since}&bucket_s=${w.bucket}`);
			if (!res.ok) return;
			const body = await res.json();
			buckets = body.buckets ?? [];
			window_ = { ...w, now: Date.now() / 1000 };
		} catch {
			// The next poll tries again.
		}
	}

	$effect(() => {
		void span;
		void ctx.machine?.url;
		load();
		const id = setInterval(load, 15000);
		return () => clearInterval(id);
	});

	function sum(list: Bucket[], key: keyof Omit<Bucket, 't'>): number {
		return list.reduce((a, b) => a + b[key], 0);
	}

	const recent = $derived(buckets.filter((b) => b.t >= window_.now - RECENT_S));
	const classified_rate = $derived((sum(recent, 'classified') * 60) / RECENT_S);
	const feed_rate = $derived((sum(recent, 'seen') * 60) / RECENT_S);
	const seen_n = $derived(sum(buckets, 'seen'));
	const multi_pct = $derived(seen_n ? (sum(buckets, 'multi_drop') / seen_n) * 100 : null);
	const classified_pct = $derived(seen_n ? (sum(buckets, 'classified') / seen_n) * 100 : null);

	// The graph: one point per bucket, empty buckets as zero.
	const W = 300;
	const H = 90;
	const series = $derived.by(() => {
		const { since, bucket, now } = window_;
		const n = Math.max(1, Math.ceil((now - since) / bucket));
		const byIndex = new Map(buckets.map((b) => [Math.round((b.t - since) / bucket), b]));
		const pts = Array.from({ length: n }, (_, i) => {
			const b = byIndex.get(i);
			const seen = b?.seen ?? 0;
			return {
				feed: (seen * 60) / bucket,
				classified: ((b?.classified ?? 0) * 60) / bucket,
				multi: seen ? ((b?.multi_drop ?? 0) / seen) * 100 : null
			};
		});
		const ppmMax = Math.max(1, ...pts.map((p) => p.feed));
		const pctMax = Math.max(25, ...pts.map((p) => p.multi ?? 0));
		const x = (i: number) => (n === 1 ? W : (i / (n - 1)) * W);
		const line = (vals: (number | null)[], max: number) =>
			vals
				.map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${(H - (v / max) * H).toFixed(1)}`))
				.filter((p) => p !== null)
				.join(' ');
		return {
			ppmMax,
			pctMax,
			feed: line(pts.map((p) => p.feed), ppmMax),
			classified: line(pts.map((p) => p.classified), ppmMax),
			multi: line(pts.map((p) => p.multi), pctMax)
		};
	});

	function fmtRate(n: number): string {
		return Number.isFinite(n) ? n.toFixed(1) : '–';
	}

	function fmtPct(n: number | null): string {
		return n == null || !Number.isFinite(n) ? '–' : `${n.toFixed(0)}%`;
	}
</script>

<div class="h-full overflow-y-auto">
	<div class="grid grid-cols-2 gap-px bg-line">
		<div class="bg-surface">
			<Stat label="Classified a minute" value={fmtRate(classified_rate)} unit="ppm" hint="Last 5 min" />
		</div>
		<div class="bg-surface">
			<Stat label="Fed a minute" value={fmtRate(feed_rate)} unit="ppm" hint="Pieces seen, last 5 min" />
		</div>
		<div class="bg-surface">
			<Stat label="Multi-drop rate" value={fmtPct(multi_pct)} hint="Of pieces seen" />
		</div>
		<div class="bg-surface">
			<Stat label="Classified" value={fmtPct(classified_pct)} hint="Of pieces seen" />
		</div>
	</div>

	<div class="border-t border-line px-4 py-3">
		<div class="flex items-center justify-between gap-3">
			<SegmentedControl bind:value={span} options={SPANS} label="Time span" size="sm" />
			<span class="num text-sm text-ink-muted">{seen_n} pieces</span>
		</div>
		<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" class="mt-3 block h-24 w-full overflow-visible">
			<line x1="0" y1={H} x2={W} y2={H} stroke="var(--color-line)" vector-effect="non-scaling-stroke" />
			<polyline points={series.feed} fill="none" stroke="var(--color-ink-muted)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
			<polyline points={series.classified} fill="none" stroke="var(--color-primary)" stroke-width="2" vector-effect="non-scaling-stroke" />
			<polyline points={series.multi} fill="none" stroke="var(--color-danger)" stroke-width="1.5" stroke-dasharray="3 3" vector-effect="non-scaling-stroke" />
		</svg>
		<div class="num mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
			<span class="flex items-center gap-1"><span class="h-0.5 w-3 bg-primary"></span>Classified/min</span>
			<span class="flex items-center gap-1"><span class="h-0.5 w-3 bg-ink-muted"></span>Fed/min</span>
			<span class="flex items-center gap-1"><span class="h-0.5 w-3 bg-danger"></span>Multi-drop %</span>
			<span class="ml-auto">top {fmtRate(series.ppmMax)} ppm · {series.pctMax.toFixed(0)}%</span>
		</div>
	</div>
</div>

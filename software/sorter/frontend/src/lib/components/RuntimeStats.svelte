<script lang="ts" module>
	export type RuntimeSpan = '10m' | '1h' | 'today';
	export const RUNTIME_SPANS: { value: RuntimeSpan; label: string }[] = [
		{ value: '10m', label: '10 min' },
		{ value: '1h', label: '1 hour' },
		{ value: 'today', label: 'Today' }
	];
</script>

<script lang="ts">
	/*
		How sorting is going over the span picked in the section's header: pieces
		classified and fed a minute, the share that were multi-drops and the share
		classified, and a graph of them over the span. Rates are per minute of
		sorting (minutes with no piece seen are left out), so a pause does not drag
		them down. Pointing at the graph shows that moment's numbers. Everything
		comes from the machine's piece records (/runtime-stats/rates), so it
		survives restarts and a tab left in the background.
	*/
	import Stat from '$lib/components/ui/Stat.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';

	type Bucket = { t: number; seen: number; classified: number; multi_drop: number };

	let { span }: { span: RuntimeSpan } = $props();

	const ctx = getMachineContext();
	const SPAN_HINT: Record<RuntimeSpan, string> = {
		'10m': 'Last 10 min',
		'1h': 'Last hour',
		today: 'Today'
	};

	let buckets = $state<Bucket[]>([]);
	let window_ = $state({ since: 0, bucket: 60, now: 0 });
	let hover = $state<number | null>(null);

	function windowFor(s: RuntimeSpan): { since: number; bucket: number } {
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
		hover = null;
		load();
		const id = setInterval(load, 15000);
		return () => clearInterval(id);
	});

	// One point per bucket over the span, empty buckets as zero.
	const points = $derived.by(() => {
		const { since, bucket, now } = window_;
		const n = Math.max(1, Math.ceil((now - since) / bucket));
		const byIndex = new Map(buckets.map((b) => [Math.round((b.t - since) / bucket), b]));
		return Array.from({ length: n }, (_, i) => {
			const b = byIndex.get(i);
			return { t: since + i * bucket, seen: b?.seen ?? 0, classified: b?.classified ?? 0, multi: b?.multi_drop ?? 0 };
		});
	});

	// Minutes of sorting: minutes (or longer buckets) in which a piece was seen.
	const sortingMinutes = $derived.by(() => {
		const slot = Math.max(window_.bucket, 60);
		const slots = new Set(points.filter((p) => p.seen > 0).map((p) => Math.floor((p.t - window_.since) / slot)));
		return (slots.size * slot) / 60;
	});

	function sum(key: 'seen' | 'classified' | 'multi'): number {
		return points.reduce((a, p) => a + p[key], 0);
	}

	// What the numbers show: the span, or the bucket under the pointer.
	const shown = $derived.by(() => {
		const p = hover == null ? null : points[hover];
		const minutes = p ? window_.bucket / 60 : sortingMinutes;
		const seen = p ? p.seen : sum('seen');
		const classified = p ? p.classified : sum('classified');
		const multi = p ? p.multi : sum('multi');
		return {
			hint: p ? timeLabel(p.t) : SPAN_HINT[span],
			classifiedRate: minutes ? classified / minutes : null,
			feedRate: minutes ? seen / minutes : null,
			multiPct: seen ? (multi / seen) * 100 : null,
			classifiedPct: seen ? (classified / seen) * 100 : null,
			seen
		};
	});

	const W = 300;
	const H = 90;
	const x = (i: number) => (points.length === 1 ? W : (i / (points.length - 1)) * W);
	const series = $derived.by(() => {
		const perMin = 60 / window_.bucket;
		const ppmMax = Math.max(1, ...points.map((p) => p.seen * perMin));
		const pctMax = Math.max(25, ...points.map((p) => (p.seen ? (p.multi / p.seen) * 100 : 0)));
		const line = (vals: (number | null)[], max: number) =>
			vals
				.map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${(H - (v / max) * H).toFixed(1)}`))
				.filter((p) => p !== null)
				.join(' ');
		return {
			ppmMax,
			pctMax,
			feed: line(points.map((p) => p.seen * perMin), ppmMax),
			classified: line(points.map((p) => p.classified * perMin), ppmMax),
			multi: line(points.map((p) => (p.seen ? (p.multi / p.seen) * 100 : null)), pctMax)
		};
	});

	function onPointer(e: PointerEvent) {
		const box = (e.currentTarget as SVGElement).getBoundingClientRect();
		const frac = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
		hover = Math.round(frac * (points.length - 1));
	}

	function timeLabel(t: number): string {
		const fmt = (s: number) => {
			const d = new Date(s * 1000);
			const h = d.getHours() % 12 || 12;
			return `${h}:${String(d.getMinutes()).padStart(2, '0')} ${d.getHours() < 12 ? 'am' : 'pm'}`;
		};
		return window_.bucket >= 300 ? `${fmt(t)} to ${fmt(t + window_.bucket)}` : `At ${fmt(t)}`;
	}

	function fmtRate(n: number | null): string {
		return n == null || !Number.isFinite(n) ? '–' : n.toFixed(1);
	}

	function fmtPct(n: number | null): string {
		return n == null || !Number.isFinite(n) ? '–' : `${n.toFixed(0)}%`;
	}
</script>

<div class="h-full overflow-y-auto">
	<div class="grid grid-cols-2 gap-px bg-line">
		<div class="bg-surface">
			<Stat label="Classified a minute" value={fmtRate(shown.classifiedRate)} unit="ppm" hint={shown.hint} />
		</div>
		<div class="bg-surface">
			<Stat label="Fed a minute" value={fmtRate(shown.feedRate)} unit="ppm" hint={shown.hint} />
		</div>
		<div class="bg-surface">
			<Stat label="Multi-drop rate" value={fmtPct(shown.multiPct)} hint="Of pieces seen" />
		</div>
		<div class="bg-surface">
			<Stat label="Classified" value={fmtPct(shown.classifiedPct)} hint="Of pieces seen" />
		</div>
	</div>

	<div class="border-t border-line px-4 py-3">
		<svg
			viewBox="0 0 {W} {H}"
			preserveAspectRatio="none"
			class="block h-24 w-full cursor-crosshair overflow-visible"
			role="img"
			aria-label="Rates over the span; point at it for a moment's numbers"
			onpointermove={onPointer}
			onpointerdown={onPointer}
			onpointerleave={() => (hover = null)}
		>
			<line x1="0" y1={H} x2={W} y2={H} stroke="var(--color-line)" vector-effect="non-scaling-stroke" />
			<polyline points={series.feed} fill="none" stroke="var(--color-ink-muted)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
			<polyline points={series.classified} fill="none" stroke="var(--color-primary)" stroke-width="2" vector-effect="non-scaling-stroke" />
			<polyline points={series.multi} fill="none" stroke="var(--color-danger)" stroke-width="1.5" stroke-dasharray="3 3" vector-effect="non-scaling-stroke" />
			{#if hover != null}
				<line x1={x(hover)} y1="0" x2={x(hover)} y2={H} stroke="var(--color-ink)" stroke-width="1" vector-effect="non-scaling-stroke" />
			{/if}
		</svg>
		<div class="num mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
			<span class="flex items-center gap-1"><span class="h-0.5 w-3 bg-primary"></span>Classified/min</span>
			<span class="flex items-center gap-1"><span class="h-0.5 w-3 bg-ink-muted"></span>Fed/min</span>
			<span class="flex items-center gap-1"><span class="h-0.5 w-3 bg-danger"></span>Multi-drop %</span>
			<span class="ml-auto">{shown.seen} pieces · top {fmtRate(series.ppmMax)} ppm · {series.pctMax.toFixed(0)}%</span>
		</div>
	</div>
</div>

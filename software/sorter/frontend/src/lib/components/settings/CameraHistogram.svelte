<script lang="ts">
	import { backendHttpBaseUrl } from '$lib/backend';
	import { onDestroy } from 'svelte';

	let { role, active = true }: { role: string; active?: boolean } = $props();

	const BINS = 64;
	const W = 280;
	const H = 80;
	const BIN_W = W / BINS;

	type HistogramData = {
		r: number[];
		g: number[];
		b: number[];
		reference_markers: Record<string, { r: number; g: number; b: number }>;
	};

	let data = $state<HistogramData | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	const REFERENCE_COLORS: Record<string, string> = {
		white: '#e2e8f0',
		black: '#374151',
		red: '#dc2626',
		green: '#16a34a',
		blue: '#2563eb',
		yellow: '#eab308'
	};

	function markerX(value: number): number {
		return (value / 256) * W;
	}

	function buildPath(bins: number[], channel: 'r' | 'g' | 'b'): string {
		if (!bins || bins.length === 0) return '';
		const points: string[] = [`M0,${H}`];
		for (let i = 0; i < bins.length; i++) {
			const x = i * BIN_W + BIN_W / 2;
			const y = H - bins[i] * H;
			points.push(`L${x.toFixed(1)},${y.toFixed(1)}`);
		}
		points.push(`L${W},${H}Z`);
		return points.join(' ');
	}

	const CHANNEL_FILL: Record<string, string> = {
		r: 'rgba(220,38,38,0.25)',
		g: 'rgba(22,163,74,0.2)',
		b: 'rgba(37,99,235,0.2)'
	};

	const CHANNEL_STROKE: Record<string, string> = {
		r: 'rgba(220,38,38,0.7)',
		g: 'rgba(22,163,74,0.6)',
		b: 'rgba(37,99,235,0.6)'
	};

	async function poll() {
		if (!active) return;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/${role}/histogram`);
			if (res.ok) {
				data = await res.json();
			}
		} catch {
			// silent — camera may not be running
		}
	}

	function startPolling() {
		stopPolling();
		poll();
		timer = setInterval(poll, 1200);
	}

	function stopPolling() {
		if (timer !== null) {
			clearInterval(timer);
			timer = null;
		}
	}

	$effect(() => {
		if (active) {
			startPolling();
		} else {
			stopPolling();
		}
	});

	onDestroy(stopPolling);
</script>

<div class="grid gap-2">
	<div class="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
		Live Histogram
	</div>
	<div class="border border-border bg-bg p-2">
		{#if data}
			<svg viewBox="0 0 {W} {H}" class="w-full" preserveAspectRatio="none">
				{#each ['b', 'g', 'r'] as ch}
					<path
						d={buildPath(data[ch as 'r' | 'g' | 'b'], ch as 'r' | 'g' | 'b')}
						fill={CHANNEL_FILL[ch]}
						stroke={CHANNEL_STROKE[ch]}
						stroke-width="1"
					/>
				{/each}

				{#each Object.entries(data.reference_markers) as [label, rgb]}
					{@const color = REFERENCE_COLORS[label] ?? '#888'}
					{@const cx = markerX((rgb.r + rgb.g + rgb.b) / 3)}
					<line
						x1={cx}
						y1={0}
						x2={cx}
						y2={H}
						stroke={color}
						stroke-width="1.5"
						stroke-dasharray="3,2"
						opacity="0.8"
					/>
				{/each}
			</svg>

			<div class="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
				{#each Object.entries(data.reference_markers) as [label, _rgb]}
					{@const color = REFERENCE_COLORS[label] ?? '#888'}
					<div class="flex items-center gap-1">
						<span
							class="inline-block h-2 w-2 shrink-0 border border-black/15"
							style="background:{color}"
						></span>
						<span class="text-[10px] capitalize text-text-muted">{label}</span>
					</div>
				{/each}
			</div>
		{:else}
			<div class="flex h-20 items-center justify-center text-xs text-text-muted">
				Waiting for frame...
			</div>
		{/if}
	</div>
</div>

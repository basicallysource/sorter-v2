<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type SystemLoad = {
		cpu_pct: number | null;
		load1: number | null;
		load5: number | null;
		cpu_count: number | null;
		memory: { total_mb: number; used_mb: number } | null;
		temp_c: number | null;
		npu_pct: number | null;
	};

	const manager = getMachinesContext();
	const POLL_MS = 2000;
	const HISTORY = 30;

	let history = $state<number[]>([]);
	let latest = $state<SystemLoad | null>(null);
	let available = $state(false);

	function httpBase(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	async function poll() {
		try {
			const res = await fetch(`${httpBase()}/api/system/load`);
			if (!res.ok) throw new Error();
			const data = (await res.json()) as SystemLoad;
			latest = data;
			if (typeof data.cpu_pct === 'number') {
				history = [...history.slice(-(HISTORY - 1)), data.cpu_pct];
				available = true;
			}
		} catch {
			available = false;
			history = [];
		}
	}

	const memPct = $derived(
		latest?.memory ? Math.round((latest.memory.used_mb / latest.memory.total_mb) * 100) : null
	);
	const cpuPct = $derived(history.length ? Math.round(history[history.length - 1]) : null);

	const sparkPoints = $derived.by(() => {
		if (history.length < 2) return '';
		const w = 56;
		const h = 18;
		const step = w / (HISTORY - 1);
		const start = HISTORY - history.length;
		return history
			.map((v, i) => `${((start + i) * step).toFixed(1)},${(h - (v / 100) * h).toFixed(1)}`)
			.join(' ');
	});

	const tooltip = $derived.by(() => {
		if (!latest) return '';
		const parts = [
			cpuPct !== null ? `CPU ${cpuPct}%` : null,
			latest.memory ? `RAM ${latest.memory.used_mb}/${latest.memory.total_mb} MB` : null,
			latest.load1 !== null ? `Load ${latest.load1} / ${latest.load5} (${latest.cpu_count} cores)` : null,
			latest.temp_c !== null ? `Temp ${Math.round(latest.temp_c)}°C` : null,
			latest.npu_pct !== null ? `NPU ${Math.round(latest.npu_pct)}%` : null
		];
		return parts.filter(Boolean).join(' · ');
	});

	onMount(() => {
		void poll();
		const interval = setInterval(() => void poll(), POLL_MS);
		return () => clearInterval(interval);
	});
</script>

{#if available && cpuPct !== null}
	<div
		class="hidden items-center gap-2 border border-border bg-surface px-2 py-1 lg:flex"
		title={tooltip}
	>
		<svg width="56" height="18" class="shrink-0" aria-hidden="true">
			<polyline
				points={sparkPoints}
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				class={cpuPct > 85 ? 'text-danger' : cpuPct > 60 ? 'text-warning' : 'text-success'}
			/>
		</svg>
		<div class="flex flex-col leading-tight">
			<span class="font-mono text-xs text-text">CPU {cpuPct}%</span>
			{#if memPct !== null}
				<span class="font-mono text-xs text-text-muted">RAM {memPct}%</span>
			{/if}
		</div>
		{#if latest?.temp_c !== null && latest?.temp_c !== undefined}
			<span class="font-mono text-xs {latest.temp_c > 80 ? 'text-danger' : 'text-text-muted'}">
				{Math.round(latest.temp_c)}°
			</span>
		{/if}
	</div>
{/if}

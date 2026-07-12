<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type MemoryLoad = {
		total_mb: number;
		used_mb: number;
		available_mb?: number | null;
		buffers_mb?: number | null;
		cache_mb?: number | null;
		swap_total_mb?: number | null;
		swap_used_mb?: number | null;
	};

	type ProcessLoad = {
		pid: number;
		name: string;
		cpu_pct?: number | null;
		mem_pct?: number | null;
		rss_mb?: number | null;
	};

	type ThermalZone = {
		name?: string | null;
		label: string;
		temp_c: number;
	};

	type SystemLoad = {
		cpu_pct: number | null;
		cpu_cores?: number[] | null;
		load1: number | null;
		load5: number | null;
		cpu_count: number | null;
		memory: MemoryLoad | null;
		temp_c: number | null;
		thermal_zones?: ThermalZone[] | null;
		npu_pct: number | null;
		processes?: {
			cpu?: ProcessLoad[];
			memory?: ProcessLoad[];
		} | null;
	};

	const manager = getMachinesContext();
	const POLL_MS = 2000;
	const HISTORY = 30;

	let history = $state<number[]>([]);
	let latest = $state<SystemLoad | null>(null);
	let available = $state(false);
	let dropdownOpen = $state(false);

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
			dropdownOpen = false;
		}
	}

	const memPct = $derived(
		latest?.memory ? Math.round((latest.memory.used_mb / latest.memory.total_mb) * 100) : null
	);
	const cpuPct = $derived(history.length ? Math.round(history[history.length - 1]) : null);
	const cpuCores = $derived(latest?.cpu_cores ?? []);
	const thermalZones = $derived(latest?.thermal_zones ?? []);
	const hottestZone = $derived.by(() => {
		if (!thermalZones.length) return null;
		return thermalZones.reduce((hottest, zone) =>
			zone.temp_c > hottest.temp_c ? zone : hottest
		);
	});
	const topCpuProcesses = $derived(latest?.processes?.cpu ?? []);
	const topMemoryProcesses = $derived(latest?.processes?.memory ?? []);

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
			latest.load1 !== null
				? `Load ${latest.load1} / ${latest.load5} (${latest.cpu_count} cores)`
				: null,
			latest.temp_c !== null ? `Temp ${Math.round(latest.temp_c)}°C` : null,
			latest.npu_pct !== null ? `NPU ${Math.round(latest.npu_pct)}%` : null
		];
		return parts.filter(Boolean).join(' · ');
	});

	function toggleDropdown() {
		dropdownOpen = !dropdownOpen;
	}

	function handleClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (!target.closest('.system-load-widget')) {
			dropdownOpen = false;
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			dropdownOpen = false;
		}
	}

	function pctLabel(value: number | null | undefined) {
		return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}%` : '-';
	}

	function decimalPctLabel(value: number | null | undefined) {
		return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '-';
	}

	function mbLabel(value: number | null | undefined) {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
		if (value >= 1024) {
			const gb = value / 1024;
			return `${gb >= 10 ? gb.toFixed(0) : gb.toFixed(1)} GB`;
		}
		return `${value} MB`;
	}

	function tempLabel(value: number | null | undefined) {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
		return `${Math.round(value)}°C`;
	}

	function tempClass(value: number | null | undefined) {
		if (typeof value !== 'number' || !Number.isFinite(value)) return 'text-text-muted';
		if (value >= 80) return 'text-danger';
		if (value >= 65) return 'text-warning';
		return 'text-text';
	}

	function thermalLabel(label: string) {
		return label
			.replace(/-thermal$/i, '')
			.replace(/_/g, ' ')
			.replace(/\b\w/g, (letter) => letter.toUpperCase());
	}

	function boundedPct(value: number | null | undefined, total = 100) {
		if (typeof value !== 'number' || !Number.isFinite(value) || total <= 0) return 0;
		return Math.max(0, Math.min(100, (value / total) * 100));
	}

	function directWidth(value: number | null | undefined) {
		return `${boundedPct(value)}%`;
	}

	function memoryWidth(value: number | null | undefined) {
		return `${boundedPct(value, latest?.memory?.total_mb ?? 0)}%`;
	}

	onMount(() => {
		void poll();
		const interval = setInterval(() => void poll(), POLL_MS);
		return () => clearInterval(interval);
	});
</script>

<svelte:window onclick={handleClickOutside} onkeydown={handleKeydown} />

{#if available && cpuPct !== null}
	<div class="system-load-widget relative hidden lg:block">
		<button
			type="button"
			onclick={toggleDropdown}
			class="flex items-center gap-2 border border-border bg-surface px-2 py-1 transition-colors hover:bg-bg {dropdownOpen
				? 'border-primary/60 bg-bg'
				: ''}"
			title={tooltip}
			aria-haspopup="dialog"
			aria-expanded={dropdownOpen}
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
					{tempLabel(latest.temp_c)}
				</span>
			{/if}
		</button>

		{#if dropdownOpen && latest}
			<div
				class="absolute top-full right-0 z-50 mt-1 w-[360px] border border-border bg-surface shadow-lg"
				role="dialog"
				aria-label="System load details"
			>
				<div class="border-b border-border px-3 py-2">
					<div class="flex items-center justify-between gap-3">
						<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							System Load
						</span>
						<span class="font-mono text-xs text-text">{pctLabel(cpuPct)} CPU</span>
					</div>
					<div class="mt-2 grid grid-cols-3 gap-2">
						<div>
							<div class="text-[11px] text-text-muted">Load</div>
							<div class="font-mono text-xs text-text">
								{latest.load1 ?? '-'} / {latest.load5 ?? '-'}
							</div>
						</div>
						<div>
							<div class="text-[11px] text-text-muted">Cores</div>
							<div class="font-mono text-xs text-text">{latest.cpu_count ?? '-'}</div>
						</div>
						<div>
							<div class="text-[11px] text-text-muted">NPU</div>
							<div class="font-mono text-xs text-text">{pctLabel(latest.npu_pct)}</div>
						</div>
					</div>
				</div>

				{#if cpuCores.length}
					<div class="border-b border-border px-3 py-2">
						<div class="mb-2 flex items-center justify-between gap-3">
							<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
								CPU Cores
							</span>
							{#if latest.temp_c !== null}
								<span class="font-mono text-xs {tempClass(latest.temp_c)}">
									{tempLabel(latest.temp_c)}
								</span>
							{/if}
						</div>
						<div class="grid grid-cols-2 gap-x-3 gap-y-1.5">
							{#each cpuCores as core, index}
								<div class="flex min-w-0 items-center gap-1.5">
									<span class="w-8 shrink-0 font-mono text-[10px] text-text-muted">CPU{index}</span>
									<div class="h-1.5 min-w-0 flex-1 bg-border">
										<div
											class="h-full {core > 85
												? 'bg-danger'
												: core > 60
													? 'bg-warning'
													: 'bg-success'}"
											style:width={directWidth(core)}
										></div>
									</div>
									<span class="w-8 shrink-0 text-right font-mono text-[10px] text-text">
										{pctLabel(core)}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if thermalZones.length}
					<div class="border-b border-border px-3 py-2">
						<div class="mb-2 flex items-center justify-between gap-3">
							<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
								Temperatures
							</span>
							{#if hottestZone}
								<span class="font-mono text-xs {tempClass(hottestZone.temp_c)}">
									{thermalLabel(hottestZone.label)} {tempLabel(hottestZone.temp_c)}
								</span>
							{/if}
						</div>
						<div class="grid grid-cols-2 gap-x-3 gap-y-1.5">
							{#each thermalZones as zone}
								<div class="grid min-w-0 grid-cols-[minmax(0,1fr)_3.2rem] items-center gap-2">
									<span class="truncate text-[11px] text-text-muted" title={zone.label}>
										{thermalLabel(zone.label)}
									</span>
									<span class="text-right font-mono text-[10px] {tempClass(zone.temp_c)}">
										{tempLabel(zone.temp_c)}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if latest.memory}
					<div class="border-b border-border px-3 py-2">
						<div class="mb-2 flex items-center justify-between gap-3">
							<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
								Memory
							</span>
							<span class="font-mono text-xs text-text">
								{mbLabel(latest.memory.used_mb)} / {mbLabel(latest.memory.total_mb)}
							</span>
						</div>
						<div class="space-y-1.5">
							<div class="grid grid-cols-[4.8rem_minmax(0,1fr)_4rem] items-center gap-2">
								<span class="text-[11px] text-text-muted">Used</span>
								<div class="h-1.5 bg-border">
									<div
										class="h-full bg-warning"
										style:width={memoryWidth(latest.memory.used_mb)}
									></div>
								</div>
								<span class="text-right font-mono text-[10px] text-text">
									{pctLabel(memPct)}
								</span>
							</div>
							<div class="grid grid-cols-[4.8rem_minmax(0,1fr)_4rem] items-center gap-2">
								<span class="text-[11px] text-text-muted">Available</span>
								<div class="h-1.5 bg-border">
									<div
										class="h-full bg-success"
										style:width={memoryWidth(latest.memory.available_mb)}
									></div>
								</div>
								<span class="text-right font-mono text-[10px] text-text">
									{mbLabel(latest.memory.available_mb)}
								</span>
							</div>
							<div class="grid grid-cols-[4.8rem_minmax(0,1fr)_4rem] items-center gap-2">
								<span class="text-[11px] text-text-muted">Cache</span>
								<div class="h-1.5 bg-border">
									<div
										class="h-full bg-primary/70"
										style:width={memoryWidth(latest.memory.cache_mb)}
									></div>
								</div>
								<span class="text-right font-mono text-[10px] text-text">
									{mbLabel(latest.memory.cache_mb)}
								</span>
							</div>
							{#if latest.memory.swap_total_mb}
								<div class="grid grid-cols-[4.8rem_minmax(0,1fr)_4rem] items-center gap-2">
									<span class="text-[11px] text-text-muted">Swap</span>
									<div class="h-1.5 bg-border">
										<div
											class="h-full bg-danger"
											style:width={boundedPct(
												latest.memory.swap_used_mb,
												latest.memory.swap_total_mb
											) + '%'}
										></div>
									</div>
									<span class="text-right font-mono text-[10px] text-text">
										{mbLabel(latest.memory.swap_used_mb)}
									</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				<div class="grid grid-cols-2 gap-3 px-3 py-2">
					<div class="min-w-0">
						<div class="mb-1.5 text-xs font-semibold tracking-wider text-text-muted uppercase">
							Top CPU
						</div>
						{#if topCpuProcesses.length}
							<div class="space-y-1">
								{#each topCpuProcesses as process}
									<div class="grid grid-cols-[minmax(0,1fr)_3.2rem] items-center gap-2">
										<span
											class="truncate text-xs text-text"
											title={`${process.name} (${process.pid})`}
										>
											{process.name}
										</span>
										<span class="text-right font-mono text-[10px] text-text-muted">
											{decimalPctLabel(process.cpu_pct)}
										</span>
									</div>
								{/each}
							</div>
						{:else}
							<div class="text-xs text-text-muted">Sampling</div>
						{/if}
					</div>

					<div class="min-w-0">
						<div class="mb-1.5 text-xs font-semibold tracking-wider text-text-muted uppercase">
							Top RAM
						</div>
						{#if topMemoryProcesses.length}
							<div class="space-y-1">
								{#each topMemoryProcesses as process}
									<div class="grid grid-cols-[minmax(0,1fr)_3.6rem] items-center gap-2">
										<span
											class="truncate text-xs text-text"
											title={`${process.name} (${process.pid})`}
										>
											{process.name}
										</span>
										<span class="text-right font-mono text-[10px] text-text-muted">
											{mbLabel(process.rss_mb)}
										</span>
									</div>
								{/each}
							</div>
						{:else}
							<div class="text-xs text-text-muted">No RSS</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	</div>
{/if}

<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import AlertTriangle from '@lucide/svelte/icons/triangle-alert';
	import CheckCircle2 from '@lucide/svelte/icons/circle-check';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import { onMount } from 'svelte';

	type SectorState = 'free' | 'occupied' | 'handoff' | 'exit';

	type Sector = {
		sector_index: number;
		state: SectorState;
		occupied: boolean;
		detection_count: number;
		max_confidence: number;
		track_ids: unknown[];
	};

	type Detection = {
		bbox: number[];
		angle_deg: number;
		sector_index: number;
	};

	type SectorOccupancyPayload = {
		ok: boolean;
		message?: string;
		frame_resolution?: [number, number];
		sector_count?: number;
		sector_size_deg?: number;
		sector_offset_deg?: number | null;
		phase_ok?: boolean;
		handoff_sector?: number | null;
		exit_sector?: number | null;
		candidate_bboxes?: number[][];
		detections?: Detection[];
		sectors?: Sector[];
	};

	let loading = $state(false);
	let error = $state('');
	let payload = $state<SectorOccupancyPayload | null>(null);
	let lastScan = $state<Date | null>(null);

	const sectors = $derived(payload?.sectors ?? []);
	const occupiedCount = $derived(sectors.filter((sector) => sector.occupied).length);
	const candidateCount = $derived(payload?.candidate_bboxes?.length ?? 0);
	const detectionCount = $derived(payload?.detections?.length ?? 0);
	const phaseText = $derived(
		payload?.sector_offset_deg === null || payload?.sector_offset_deg === undefined
			? 'n/a'
			: `${payload.sector_offset_deg.toFixed(1)}°`
	);
	const frameText = $derived(
		payload?.frame_resolution ? `${payload.frame_resolution[0]} x ${payload.frame_resolution[1]}` : 'n/a'
	);

	function sectorClass(sector: Sector): string {
		if (sector.occupied) {
			return 'border-primary bg-primary-soft text-ink';
		}
		if (sector.state === 'handoff') {
			return 'border-warning bg-warning-soft text-ink';
		}
		if (sector.state === 'exit') {
			return 'border-info bg-info-soft text-ink';
		}
		return 'border-line bg-well text-ink-muted';
	}

	function sectorLabel(sector: Sector): string {
		if (sector.occupied) return 'Occupied';
		if (sector.state === 'handoff') return 'Handoff';
		if (sector.state === 'exit') return 'Exit';
		return 'Free';
	}

	async function scan(): Promise<void> {
		loading = true;
		error = '';
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/classification-channel/sector-occupancy`,
				{ method: 'POST' }
			);
			const data = (await res.json().catch(() => ({}))) as SectorOccupancyPayload | { detail?: string };
			if (!res.ok) {
				const detail = 'detail' in data && typeof data.detail === 'string' ? data.detail : null;
				throw new Error(detail ?? `HTTP ${res.status}`);
			}
			payload = data as SectorOccupancyPayload;
			if (!payload.ok) {
				error = payload.message ?? 'C4 sector scan failed.';
			}
			lastScan = new Date();
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void scan();
	});
</script>

<div class="flex flex-col gap-4">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
			<span class="inline-flex items-center gap-1.5">
				{#if payload?.phase_ok}
					<CheckCircle2 size={13} class="text-success-ink" />
				{:else}
					<AlertTriangle size={13} class="text-warning-ink" />
				{/if}
				Phase {phaseText}
			</span>
			<span>{frameText}</span>
			<span>{occupiedCount}/5 occupied</span>
			{#if lastScan}
				<span>{lastScan.toLocaleTimeString()}</span>
			{/if}
		</div>
		<button
			type="button"
			onclick={() => scan()}
			disabled={loading}
			class="inline-flex items-center gap-1.5 border border-line bg-well px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
			title="Scan C4 sectors"
		>
			<RefreshCw size={13} class={loading ? 'animate-spin' : ''} />
			{loading ? 'Scanning' : 'Scan'}
		</button>
	</div>

	{#if error}
		<div class="border border-warning bg-warning-soft px-3 py-2 text-sm text-ink">
			<div class="flex items-start gap-2">
				<AlertTriangle size={15} class="mt-0.5 shrink-0 text-warning-ink" />
				<span>{error}</span>
			</div>
		</div>
	{/if}

	<div class="grid grid-cols-5 gap-2">
		{#each sectors as sector (sector.sector_index)}
			<div class={`min-h-24 border px-3 py-2 ${sectorClass(sector)}`}>
				<div class="flex items-start justify-between gap-2">
					<div class="text-sm font-semibold">S{sector.sector_index + 1}</div>
					<div class="text-xs">{sectorLabel(sector)}</div>
				</div>
				<div class="mt-3 grid gap-1 text-xs">
					<div>Detections {sector.detection_count}</div>
					<div>Confidence {sector.max_confidence.toFixed(2)}</div>
				</div>
			</div>
		{/each}
		{#if sectors.length === 0}
			{#each Array.from({ length: 5 }) as _, index (index)}
				<div class="min-h-24 border border-dashed border-line bg-well px-3 py-2 text-ink-muted">
					<div class="text-sm font-semibold">S{index + 1}</div>
				</div>
			{/each}
		{/if}
	</div>

	{#if payload}
		<div class="grid gap-2 text-xs text-ink-muted sm:grid-cols-4">
			<div class="border border-line bg-well px-3 py-2">
				<div class="font-medium text-ink">Candidates</div>
				<div>{candidateCount}</div>
			</div>
			<div class="border border-line bg-well px-3 py-2">
				<div class="font-medium text-ink">Detections</div>
				<div>{detectionCount}</div>
			</div>
			<div class="border border-line bg-well px-3 py-2">
				<div class="font-medium text-ink">Handoff</div>
				<div>{payload.handoff_sector === null || payload.handoff_sector === undefined ? 'n/a' : `S${payload.handoff_sector + 1}`}</div>
			</div>
			<div class="border border-line bg-well px-3 py-2">
				<div class="font-medium text-ink">Exit</div>
				<div>{payload.exit_sector === null || payload.exit_sector === undefined ? 'n/a' : `S${payload.exit_sector + 1}`}</div>
			</div>
		</div>
	{/if}
</div>

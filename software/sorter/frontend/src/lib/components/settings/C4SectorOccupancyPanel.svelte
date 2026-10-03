<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import AlertTriangle from '@lucide/svelte/icons/triangle-alert';
	import CheckCircle2 from '@lucide/svelte/icons/circle-check';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
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
		if (sector.occupied) return 'bg-primary-soft text-ink';
		if (sector.state === 'handoff') return 'bg-warning-soft text-ink';
		if (sector.state === 'exit') return 'bg-info-soft text-ink';
		return 'bg-well text-ink-muted';
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

<Panel title="C4 sectors" flush>
	{#snippet actions()}
		<Button size="sm" icon={RefreshCw} {loading} onclick={() => scan()}>Scan</Button>
	{/snippet}
	<div class="flex flex-col gap-4 px-(--pad-panel) pb-(--pad-panel)">
		<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-muted">
			<span class="inline-flex items-center gap-1.5">
				{#if payload?.phase_ok}
					<CheckCircle2 size={14} class="text-success-ink" />
				{:else}
					<AlertTriangle size={14} class="text-warning-ink" />
				{/if}
				Phase {phaseText}
			</span>
			<span>{frameText}</span>
			<span class="num">{occupiedCount} of 5 occupied</span>
			{#if lastScan}<span class="num">{lastScan.toLocaleTimeString()}</span>{/if}
		</div>
		{#if error}<Alert tone="warning">{error}</Alert>{/if}
		<div class="grid grid-cols-3 gap-2 sm:grid-cols-5">
			{#each sectors as sector (sector.sector_index)}
				<div class="min-h-24 rounded-control px-3 py-2 text-sm {sectorClass(sector)}">
					<div class="flex items-start justify-between gap-2">
						<span class="font-medium">S{sector.sector_index + 1}</span>
						<span>{sectorLabel(sector)}</span>
					</div>
					<div class="num mt-3 grid gap-0.5 text-ink-muted">
						<span>Detections {sector.detection_count}</span>
						<span>Confidence {sector.max_confidence.toFixed(2)}</span>
					</div>
				</div>
			{/each}
			{#if sectors.length === 0}
				{#each Array.from({ length: 5 }) as _, index (index)}
					<div class="min-h-24 rounded-control bg-well px-3 py-2 text-sm font-medium text-ink-muted">
						S{index + 1}
					</div>
				{/each}
			{/if}
		</div>
	</div>
	{#if payload}
		{@const sectorName = (i: number | null | undefined) => (i == null ? 'None' : `S${i + 1}`)}
		<div class="grid grid-cols-2 gap-px border-t border-line bg-line sm:grid-cols-4">
			<div class="bg-surface"><Stat label="Candidates" value={candidateCount} /></div>
			<div class="bg-surface"><Stat label="Detections" value={detectionCount} /></div>
			<div class="bg-surface"><Stat label="Handoff" value={sectorName(payload.handoff_sector)} /></div>
			<div class="bg-surface"><Stat label="Exit" value={sectorName(payload.exit_sector)} /></div>
		</div>
	{/if}
</Panel>

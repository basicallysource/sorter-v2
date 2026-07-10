<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import TuningParamRow from '$lib/components/settings/TuningParamRow.svelte';
	import { groupTuningSections, type TuningFieldMeta, type TuningValues } from '$lib/settings/tuning';

	type BeltStatus = {
		ts: number;
		reason: string;
		commanded_speed_usteps_per_s?: number;
		target_speed_usteps_per_s?: number;
		base_speed_usteps_per_s?: number | null;
		c3_pieces?: number | null;
		c3_full_speed_pieces?: number | null;
		c3_stop_pieces?: number | null;
		running_for_s?: number | null;
		since_last_arrival_s?: number | null;
		jam_timeout_s?: number | null;
		jam_countdown_s?: number | null;
	};

	let fields = $state<TuningFieldMeta[]>([]);
	let values = $state<TuningValues>({});
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);
	let beltStatus = $state<BeltStatus | null>(null);
	let beltStatusAvailable = $state(false);

	let sections = $derived(groupTuningSections(fields));
	// Status older than ~3 s means the belt flow is not ticking (feeder idle,
	// different feeder mode, or backend restart) — show it greyed out.
	let statusFresh = $derived(
		beltStatus !== null && Date.now() / 1000 - beltStatus.ts < 3
	);

	const REASON_LABELS: Record<string, string> = {
		running: 'Running at full speed',
		throttled: 'Throttled — C3 filling up',
		stopped_c3_full: 'Stopped — C3 full',
		disabled: 'Stopped — belt disabled in config',
		no_perception: 'Stopped — no C3 perception state yet',
		no_belt_stepper: 'Stopped — no belt stepper bound',
		idle: 'Idle — feeder not in FEEDING state'
	};

	function speedPct(s: BeltStatus): string {
		const base = s.base_speed_usteps_per_s ?? 0;
		if (!base) return '—';
		return `${Math.round((Math.abs(s.commanded_speed_usteps_per_s ?? 0) / base) * 100)}%`;
	}

	async function pollStatus() {
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-belt/status`);
			if (!res.ok) return;
			const data = await res.json();
			beltStatusAvailable = Boolean(data.available);
			beltStatus = data.status ?? null;
		} catch {
			// Transient fetch errors just keep the last snapshot.
		}
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-belt`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			fields = data.fields;
			values = { ...data.config };
		} catch (e: any) {
			error = e.message ?? 'Failed to load config';
		} finally {
			loading = false;
		}
	}

	async function save() {
		saving = true;
		saved = false;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-belt`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(values)
			});
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			values = { ...data.config };
			saved = true;
			setTimeout(() => (saved = false), 3000);
		} catch (e: any) {
			error = e.message ?? 'Failed to save config';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		load();
		void pollStatus();
		const interval = setInterval(() => void pollStatus(), 1000);
		return () => clearInterval(interval);
	});
</script>

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">B1 Belt Feeder Tuning</div>
		<div class="mt-1 text-sm text-text-muted">
			The B1 cleated conveyor runs continuously and is throttled by C3's fill level: full speed
			while C3 has at most the full-speed piece count, ramping linearly down to a stop at the stop
			count. C3's own exit metering into the classification channel is tuned on the Feeder Simple
			Pulse page. Changes take effect within ~1 second (no restart needed).
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if saved}
		<Alert variant="success">Saved. Changes apply within ~1 second.</Alert>
	{/if}

	<SectionCard
		title="Live status"
		description="What the belt controller is doing right now — why the belt moves (or doesn't), the C3 fill level driving the ramp, and the jam countdown."
	>
		{#if !beltStatusAvailable || beltStatus === null}
			<div class="text-sm text-text-muted">
				No belt controller active yet. The status appears once the machine runs the belt_feeder
				setup and feeding has started.
			</div>
		{:else}
			<div class="flex flex-col gap-3 {statusFresh ? '' : 'opacity-50'}">
				{#if !statusFresh}
					<div class="text-sm text-text-muted">
						Stale snapshot — the belt flow is not ticking right now (feeder idle or paused).
					</div>
				{/if}
				<div
					class="text-sm font-medium {beltStatus.reason === 'running' ||
					beltStatus.reason === 'throttled'
						? 'text-success'
						: 'text-text'}"
				>
					{REASON_LABELS[beltStatus.reason] ?? beltStatus.reason}
				</div>
				<div class="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
					<div>
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">Speed</div>
						<div class="text-sm text-text tabular-nums">
							{Math.abs(beltStatus.commanded_speed_usteps_per_s ?? 0)} µsteps/s ({speedPct(
								beltStatus
							)})
						</div>
					</div>
					<div>
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							C3 pieces
						</div>
						<div class="text-sm text-text tabular-nums">
							{beltStatus.c3_pieces ?? '—'} (full ≤{beltStatus.c3_full_speed_pieces ?? '—'}, stop
							≥{beltStatus.c3_stop_pieces ?? '—'})
						</div>
					</div>
					<div>
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							Running for
						</div>
						<div class="text-sm text-text tabular-nums">
							{beltStatus.running_for_s != null ? `${beltStatus.running_for_s}s` : '—'}
						</div>
					</div>
					<div>
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							Last piece into C3
						</div>
						<div class="text-sm text-text tabular-nums">
							{beltStatus.since_last_arrival_s != null
								? `${beltStatus.since_last_arrival_s}s ago`
								: 'none yet'}
						</div>
					</div>
					<div>
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							Jam countdown
						</div>
						<div class="text-sm text-text tabular-nums">
							{beltStatus.jam_countdown_s != null
								? `${beltStatus.jam_countdown_s}s of ${beltStatus.jam_timeout_s}s`
								: '—'}
						</div>
					</div>
				</div>
			</div>
		{/if}
	</SectionCard>

	<SectionCard
		title="Parameters"
		description="Belt speed, the C3 fill-level ramp, and jam detection for the B1 belt topology."
	>
		{#if loading}
			<div class="text-sm text-text-muted">Loading…</div>
		{:else}
			<div class="flex flex-col gap-8">
				{#each sections as section}
					<div class="flex flex-col gap-4">
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							{section.name}
						</div>
						{#each section.fields as field}
							<TuningParamRow {field} bind:values />
						{/each}
					</div>
				{/each}
			</div>

			<div class="mt-6 flex gap-3">
				<Button variant="primary" onclick={save} loading={saving}>Save</Button>
				<Button variant="secondary" onclick={load} disabled={saving}>Reset to saved</Button>
			</div>
		{/if}
	</SectionCard>
</div>

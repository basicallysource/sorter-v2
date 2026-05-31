<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StallGuardChart from '$lib/components/StallGuardChart.svelte';

	const STEPPERS = ['carousel', 'chute', 'c_channel_1', 'c_channel_2', 'c_channel_3'];
	const DEFAULT_TCOOLTHRS = 1048575; // 0xFFFFF — StallGuard active across the speed range

	type Run = {
		id: string;
		started_at: number;
		ended_at: number | null;
		source: string;
		stepper_name: string | null;
		label: string | null;
		status: string;
		params: any;
		sample_count: number;
		sg_min: number | null;
		sg_max: number | null;
		sg_mean: number | null;
		suggested_sgthrs: number | null;
	};
	type SummaryRow = {
		stepper_name: string;
		samples: number;
		sg_min: number;
		sg_max: number;
		sg_mean: number;
		last_seen: number;
	};
	type ChartPoint = { x: number; sg: number | null; cs: number | null; tstep: number | null };

	let runs = $state<Run[]>([]);
	let summary = $state<SummaryRow[]>([]);
	let selectedRun = $state<Run | null>(null);
	let points = $state<ChartPoint[]>([]);
	let loadingSamples = $state(false);
	let error = $state<string | null>(null);
	let notice = $state<string | null>(null);
	let showCs = $state(false);
	let showTstep = $state(false);

	// Sweep form
	let swStepper = $state('carousel');
	let swSpeed = $state(1500);
	let swDirection = $state<'cw' | 'ccw'>('cw');
	let swDuration = $state(4);
	let swLoaded = $state(false);
	let swLabel = $state('');
	let swEnterToRun = $state(false);
	let running = $state(false);
	let savingThreshold = $state(false);

	const base = () => getBackendHttpBase();

	function onKeydown(ev: KeyboardEvent) {
		if (!swEnterToRun || ev.key !== 'Enter' || running) return;
		ev.preventDefault();
		runSweep();
	}

	function fmtTime(epoch: number | null): string {
		if (!epoch) return '—';
		return new Date(epoch * 1000).toLocaleString();
	}

	async function loadRuns() {
		try {
			const res = await fetch(`${base()}/api/stepper-telemetry/runs?limit=200`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			runs = (await res.json()).runs;
		} catch (e: any) {
			error = e.message ?? 'Failed to load runs';
		}
	}

	async function loadSummary() {
		try {
			const res = await fetch(`${base()}/api/stepper-telemetry/summary`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			summary = (await res.json()).steppers;
		} catch (e: any) {
			error = e.message ?? 'Failed to load summary';
		}
	}

	async function selectRun(run: Run) {
		selectedRun = run;
		loadingSamples = true;
		points = [];
		error = null;
		try {
			const res = await fetch(`${base()}/api/stepper-telemetry/runs/${run.id}/samples`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			const rows = data.samples as any[];
			const t0 = rows.length ? rows[0].recorded_at : 0;
			points = rows.map((r) => ({
				x: r.recorded_at - t0,
				sg: r.sg_result,
				cs: r.cs_actual,
				tstep: r.tstep,
			}));
		} catch (e: any) {
			error = e.message ?? 'Failed to load samples';
		} finally {
			loadingSamples = false;
		}
	}

	async function runSweep() {
		if (running) return;
		running = true;
		error = null;
		notice = null;
		try {
			const qs = new URLSearchParams({
				stepper: swStepper,
				speed: String(swSpeed),
				direction: swDirection,
				duration_s: String(swDuration),
				loaded: String(swLoaded),
			});
			if (swLabel.trim()) qs.set('label', swLabel.trim());
			const res = await fetch(`${base()}/stepper/stallguard-sweep?${qs}`, { method: 'POST' });
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			notice = data.stats
				? `Sweep done: ${data.stats.samples} samples, SG ${data.stats.sg_min}–${data.stats.sg_max} (mean ${data.stats.sg_mean}), suggested SGTHRS ${data.stats.suggested_sgthrs}.`
				: 'Sweep done (no valid samples).';
			await loadRuns();
			await loadSummary();
			const fresh = runs.find((r) => r.id === data.run_id);
			if (fresh) await selectRun(fresh);
		} catch (e: any) {
			error = e.message ?? 'Sweep failed';
		} finally {
			running = false;
		}
	}

	async function saveThreshold() {
		if (!selectedRun?.stepper_name || selectedRun.suggested_sgthrs == null) return;
		savingThreshold = true;
		error = null;
		notice = null;
		try {
			const res = await fetch(
				`${base()}/stepper/${selectedRun.stepper_name}/stallguard-config`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						sgthrs: selectedRun.suggested_sgthrs,
						tcoolthrs: DEFAULT_TCOOLTHRS,
						enabled: true,
					}),
				}
			);
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			notice = `Saved SGTHRS=${data.sgthrs} for ${data.toml_name} to machine.toml.`;
		} catch (e: any) {
			error = e.message ?? 'Failed to save threshold';
		} finally {
			savingThreshold = false;
		}
	}

	async function deleteRun(run: Run, ev: Event) {
		ev.stopPropagation();
		if (!confirm(`Delete run ${run.id.slice(0, 8)} and its samples?`)) return;
		try {
			const res = await fetch(`${base()}/api/stepper-telemetry/runs/${run.id}`, {
				method: 'DELETE',
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			if (selectedRun?.id === run.id) {
				selectedRun = null;
				points = [];
			}
			await loadRuns();
			await loadSummary();
		} catch (e: any) {
			error = e.message ?? 'Failed to delete run';
		}
	}

	const triggerLevel = $derived(
		selectedRun?.suggested_sgthrs != null ? selectedRun.suggested_sgthrs * 2 : null
	);

	$effect(() => {
		loadRuns();
		loadSummary();
	});
</script>

<svelte:window onkeydown={onKeydown} />

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">Stepper StallGuard Telemetry</div>
		<div class="mt-1 text-sm text-text-muted">
			Record and visualize TMC2209 load (<span class="font-mono">SG_RESULT</span>) per motor. Run
			targeted sweeps, inspect the load curve, and write a stall threshold to the machine config.
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}
	{#if notice}
		<Alert variant="success">{notice}</Alert>
	{/if}

	<SectionCard
		title="Per-motor summary"
		description="Rollup of all recorded SG_RESULT samples for each motor."
	>
		{#if summary.length === 0}
			<div class="text-sm text-text-muted">No telemetry recorded yet. Run a sweep below.</div>
		{:else}
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-border text-left text-text-muted">
						<th class="py-2 pr-4 font-medium">Motor</th>
						<th class="py-2 pr-4 font-medium">Samples</th>
						<th class="py-2 pr-4 font-medium">SG min</th>
						<th class="py-2 pr-4 font-medium">SG mean</th>
						<th class="py-2 pr-4 font-medium">SG max</th>
						<th class="py-2 pr-4 font-medium">Last seen</th>
					</tr>
				</thead>
				<tbody>
					{#each summary as row}
						<tr class="border-b border-border/50 text-text">
							<td class="py-2 pr-4 font-mono">{row.stepper_name}</td>
							<td class="py-2 pr-4">{row.samples}</td>
							<td class="py-2 pr-4">{row.sg_min}</td>
							<td class="py-2 pr-4">{Math.round(row.sg_mean)}</td>
							<td class="py-2 pr-4">{row.sg_max}</td>
							<td class="py-2 pr-4 text-text-muted">{fmtTime(row.last_seen)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</SectionCard>

	<SectionCard
		title="Run a targeted sweep"
		description="Spins one motor at constant speed and records its load curve. Use the loaded option for a deliberate stall test — hold/resist the motor by hand while it runs."
	>
		<Alert variant="warning">
			This moves a real motor. Keep the area clear and your hand near the stop control.
		</Alert>

		<div class="mt-4 flex flex-wrap items-end gap-4">
			<div class="flex flex-col gap-1">
				<label class="text-sm text-text" for="sw-stepper">Motor</label>
				<select
					id="sw-stepper"
					bind:value={swStepper}
					class="setup-control"
					style="min-width: 10rem;"
				>
					{#each STEPPERS as s}
						<option value={s}>{s}</option>
					{/each}
				</select>
			</div>
			<label class="flex w-40 flex-col gap-1 text-sm text-text">
				Speed (µsteps/s)
				<Input type="number" bind:value={swSpeed} />
			</label>
			<div class="flex flex-col gap-1">
				<label class="text-sm text-text" for="sw-dir">Direction</label>
				<select id="sw-dir" bind:value={swDirection} class="setup-control">
					<option value="cw">cw</option>
					<option value="ccw">ccw</option>
				</select>
			</div>
			<label class="flex w-32 flex-col gap-1 text-sm text-text">
				Duration (s)
				<Input type="number" bind:value={swDuration} />
			</label>
			<label class="flex w-56 flex-col gap-1 text-sm text-text">
				Label (optional)
				<Input type="text" bind:value={swLabel} />
			</label>
			<label class="flex items-center gap-2 text-sm text-text">
				<input type="checkbox" bind:checked={swLoaded} class="accent-primary" />
				Loaded (stall test)
			</label>
			<Button variant="primary" onclick={runSweep} loading={running}>Run sweep</Button>
			<label class="flex items-center gap-2 text-sm text-text">
				<input type="checkbox" bind:checked={swEnterToRun} class="accent-primary" />
				Enter to run
			</label>
		</div>
	</SectionCard>

	<div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
		<div class="lg:col-span-1">
			<SectionCard title="Runs" description="Recent recordings. Click to view.">
				{#if runs.length === 0}
					<div class="text-sm text-text-muted">No runs yet.</div>
				{:else}
					<div class="flex max-h-[28rem] flex-col overflow-y-auto">
						{#each runs as run}
							<div
								class="border-b border-border/50 {selectedRun?.id === run.id
									? 'bg-primary-light/60'
									: ''}"
							>
								<button
									type="button"
									onclick={() => selectRun(run)}
									class="flex w-full flex-col gap-1 px-2 pt-2 text-left hover:bg-primary-light/40"
								>
									<div class="flex items-center justify-between gap-2">
										<span class="font-mono text-sm text-text">{run.stepper_name ?? '—'}</span>
										<span class="text-xs uppercase tracking-wider text-text-muted">{run.source}</span>
									</div>
									<div class="text-sm text-text-muted">{fmtTime(run.started_at)}</div>
									<div class="text-sm text-text-muted">
										{run.sample_count} samples{#if run.sg_min != null}, SG {run.sg_min}–{run.sg_max}{/if}{#if run.suggested_sgthrs != null}, SGTHRS {run.suggested_sgthrs}{/if}
										{#if run.label}<span class="text-text"> · {run.label}</span>{/if}
									</div>
								</button>
								<div class="flex justify-end px-2 pb-2">
									<button
										type="button"
										onclick={(e) => deleteRun(run, e)}
										class="text-sm text-danger hover:underline"
										aria-label="Delete run">delete</button
									>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</SectionCard>
		</div>

		<div class="lg:col-span-2">
			<SectionCard title="Load curve" description="SG_RESULT over time. Lower = more load; a stall drops it toward 0.">
				{#if selectedRun}
					<div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
						<span class="text-text-muted">Motor:</span>
						<span class="font-mono text-text">{selectedRun.stepper_name}</span>
						<span class="text-text-muted">Speed:</span>
						<span class="text-text">{selectedRun.params?.speed ?? '—'} µsteps/s</span>
						<span class="text-text-muted">Dir:</span>
						<span class="text-text">{selectedRun.params?.direction ?? '—'}</span>
						<span class="text-text-muted">Duration:</span>
						<span class="text-text">{selectedRun.params?.duration_s ?? '—'} s</span>
						{#if selectedRun.sg_mean != null}
							<span class="text-text-muted">Mean SG:</span>
							<span class="text-text">{Math.round(selectedRun.sg_mean)}</span>
						{/if}
						{#if selectedRun.suggested_sgthrs != null}
							<span class="text-text-muted">Suggested SGTHRS:</span>
							<span class="text-text">{selectedRun.suggested_sgthrs}</span>
							<span class="text-text-muted">(trigger ≤ {triggerLevel})</span>
						{/if}
					</div>
					<div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
						<span class="text-text-muted">IRUN:</span>
						<span class="text-text">{selectedRun.params?.irun ?? '—'}</span>
						<span class="text-text-muted">Accel:</span>
						<span class="text-text">{selectedRun.params?.acceleration ?? '—'} µsteps/s²</span>
						<span class="text-text-muted">Microsteps:</span>
						<span class="text-text">{selectedRun.params?.microsteps ?? '—'}</span>
						<span class="text-text-muted">Chopper:</span>
						<span class="text-text">
							{selectedRun.params?.stealthchop == null
								? '—'
								: selectedRun.params.stealthchop
									? 'StealthChop'
									: 'SpreadCycle'}
						</span>
						<span class="text-text-muted">Loaded:</span>
						<span class="text-text">{selectedRun.params?.loaded ? 'yes' : 'no'}</span>
					</div>
					<div class="mb-3 flex items-center gap-4 text-sm">
						<label class="flex items-center gap-2 text-text">
							<input type="checkbox" bind:checked={showCs} class="accent-warning" /> CS_ACTUAL (norm.)
						</label>
						<label class="flex items-center gap-2 text-text">
							<input type="checkbox" bind:checked={showTstep} class="accent-success" /> TSTEP (norm.)
						</label>
					</div>

					{#if loadingSamples}
						<div class="text-sm text-text-muted">Loading samples…</div>
					{:else}
						<StallGuardChart
							{points}
							triggerLevel={triggerLevel}
							sgMean={selectedRun.sg_mean}
							{showCs}
							{showTstep}
						/>
					{/if}

					{#if selectedRun.suggested_sgthrs != null && selectedRun.stepper_name}
						<div class="mt-4">
							<Button variant="secondary" onclick={saveThreshold} loading={savingThreshold}>
								Save SGTHRS={selectedRun.suggested_sgthrs} to machine.toml
							</Button>
						</div>
					{/if}
				{:else}
					<div class="text-sm text-text-muted">Select a run to view its load curve.</div>
				{/if}
			</SectionCard>
		</div>
	</div>
</div>

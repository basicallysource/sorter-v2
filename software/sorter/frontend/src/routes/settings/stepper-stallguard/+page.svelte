<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StallGuardChart from '$lib/components/StallGuardChart.svelte';

	const STEPPERS = ['carousel', 'chute', 'c_channel_1', 'c_channel_2', 'c_channel_3'];

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
	type Profile = 'constant' | 'chute_random' | 'pulsed';
	let swStepper = $state('carousel');
	let swSpeed = $state(1500);
	let swDirection = $state<'cw' | 'ccw'>('cw');
	let swDuration = $state(4);
	let swLoaded = $state(false);
	let swLabel = $state('');
	let swEnterToRun = $state(false);
	// Motion profile. Constant spin only suits a free-running motor; the chute
	// aims to angles (random go-to + turnaround) and the rotors/carousel pulse
	// with the odd jitter — those mirror real load. Default by motor.
	let swProfile = $state<Profile>('pulsed');
	let swChuteMinDeg = $state(10);
	let swChuteMaxDeg = $state(340);
	let swMinDeltaDeg = $state(30);
	let swPulseDeg = $state(30);
	let swDwellMs = $state(250);
	let swJitterEvery = $state(5);
	// Only motion at/above cruise (TSTEP <= this; lower TSTEP = faster) counts for
	// the threshold — accel/decel/reversal transients dip SG even unloaded and
	// would drag the floor down. This is also saved as the enforcement velocity
	// floor (TCOOLTHRS) so DIAG only acts at cruise. The chute cruises at TSTEP
	// ~75-150; transients are >200.
	let swCruiseTstep = $state(150);
	let running = $state(false);
	let savingThreshold = $state(false);

	// Pair-based threshold suggestion for the selected motor — pooled from the
	// motor's recent unloaded floor + loaded stall dip (server-computed), placed
	// at the geometric midpoint of the gap. This, not any single run, drives Save.
	type Suggestion = {
		stepper: string;
		cruise_tstep: number;
		unloaded_floor: number | null;
		loaded_dip: number | null;
		trigger_level: number | null;
		suggested_sgthrs: number | null;
		enough_data: boolean;
		unloaded_runs: number;
		loaded_runs: number;
		detail: string;
	};
	let suggestion = $state<Suggestion | null>(null);

	const base = () => getBackendHttpBase();

	function defaultProfileFor(stepper: string): Profile {
		return stepper === 'chute' ? 'chute_random' : 'pulsed';
	}

	function onStepperChange() {
		swProfile = defaultProfileFor(swStepper);
	}

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

	async function loadSuggestion(motor: string) {
		suggestion = null;
		try {
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-suggestion`);
			if (!res.ok) return;
			suggestion = await res.json();
		} catch {
			suggestion = null;
		}
	}

	async function selectRun(run: Run) {
		selectedRun = run;
		loadingSamples = true;
		points = [];
		error = null;
		if (run.stepper_name) loadSuggestion(run.stepper_name);
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
				profile: swProfile,
				cruise_tstep: String(swCruiseTstep),
			});
			if (swProfile === 'chute_random') {
				qs.set('chute_min_deg', String(swChuteMinDeg));
				qs.set('chute_max_deg', String(swChuteMaxDeg));
				qs.set('min_delta_deg', String(swMinDeltaDeg));
			} else if (swProfile === 'pulsed') {
				qs.set('pulse_deg', String(swPulseDeg));
				qs.set('dwell_ms', String(swDwellMs));
				qs.set('jitter_every', String(swJitterEvery));
			}
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
			else await loadSuggestion(swStepper);
		} catch (e: any) {
			error = e.message ?? 'Sweep failed';
		} finally {
			running = false;
		}
	}

	async function saveThreshold() {
		const motor = suggestion?.stepper;
		if (!motor || suggestion?.suggested_sgthrs == null) return;
		savingThreshold = true;
		error = null;
		notice = null;
		try {
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-config`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					sgthrs: suggestion.suggested_sgthrs,
					// The cruise velocity floor is the enforcement TCOOLTHRS so DIAG only
					// acts at cruise (matching where the threshold was tuned).
					tcoolthrs: suggestion.cruise_tstep,
					enabled: true,
				}),
			});
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

	// Trigger line on the chart prefers the pair-based suggestion (the level we'd
	// actually save); falls back to the selected run's own suggestion if there's
	// not yet a loaded run to pair with.
	const triggerLevel = $derived(
		suggestion?.trigger_level != null
			? suggestion.trigger_level
			: selectedRun?.suggested_sgthrs != null
				? selectedRun.suggested_sgthrs * 2
				: null
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
		description="Drives one motor with a representative motion profile and records its load curve. Use the loaded option for a deliberate stall test — hold/resist the motor by hand while it runs."
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
					onchange={onStepperChange}
					class="setup-control"
					style="min-width: 10rem;"
				>
					{#each STEPPERS as s}
						<option value={s}>{s}</option>
					{/each}
				</select>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-sm text-text" for="sw-profile">Motion profile</label>
				<select id="sw-profile" bind:value={swProfile} class="setup-control" style="min-width: 11rem;">
					<option value="constant">constant spin</option>
					<option value="chute_random">chute: random go-to-angle</option>
					<option value="pulsed">pulsed + jitter</option>
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

		{#if swProfile === 'chute_random'}
			<div class="mt-4 flex flex-wrap items-end gap-4">
				<label class="flex w-40 flex-col gap-1 text-sm text-text">
					Min angle (output °)
					<Input type="number" bind:value={swChuteMinDeg} />
				</label>
				<label class="flex w-40 flex-col gap-1 text-sm text-text">
					Max angle (output °)
					<Input type="number" bind:value={swChuteMaxDeg} />
				</label>
				<label class="flex w-40 flex-col gap-1 text-sm text-text">
					Min angle delta (°)
					<Input type="number" bind:value={swMinDeltaDeg} />
				</label>
				<div class="max-w-md text-sm text-text-muted">
					Random go-to-angle within [min, max] output degrees (auto-clamped to the chute's safe
					travel, max 345°), with an immediate turnaround on each arrival. Homes the chute first if
					needed, so it operates on absolute angles and can never reach an endstop.
				</div>
			</div>
		{:else if swProfile === 'pulsed'}
			<div class="mt-4 flex flex-wrap items-end gap-4">
				<label class="flex w-40 flex-col gap-1 text-sm text-text">
					Pulse size (motor °)
					<Input type="number" bind:value={swPulseDeg} />
				</label>
				<label class="flex w-32 flex-col gap-1 text-sm text-text">
					Dwell (ms)
					<Input type="number" bind:value={swDwellMs} />
				</label>
				<label class="flex w-40 flex-col gap-1 text-sm text-text">
					Jitter every N pulses
					<Input type="number" bind:value={swJitterEvery} />
				</label>
				<div class="max-w-md text-sm text-text-muted">
					Discrete pulses with a dwell between (how the rotors and carousel actually run), with an
					unstick jitter every N pulses. Only the moving phases are sampled. Set jitter to 0 to
					disable it.
				</div>
			</div>
		{/if}

		<div class="mt-4 flex flex-wrap items-end gap-4 border-t border-border/40 pt-4">
			<label class="flex w-44 flex-col gap-1 text-sm text-text">
				Cruise TSTEP (threshold)
				<Input type="number" bind:value={swCruiseTstep} />
			</label>
			<div class="max-w-lg text-sm text-text-muted">
				Only motion at cruise (TSTEP ≤ this; lower = faster) sets the threshold — the accel/decel and
				reversal transients dip SG even unloaded and would drag the floor down. Stays in StealthChop
				(the TMC2209's StallGuard works there, not SpreadCycle). The chute cruises at TSTEP ~75–150;
				saved as the enforcement velocity floor so DIAG only acts at cruise.
			</div>
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
						<span class="text-text-muted">Cruise TSTEP:</span>
						<span class="text-text">{selectedRun.params?.cruise_tstep ?? '—'}</span>
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

					{#if suggestion}
						<div class="mt-4 border border-border bg-bg px-4 py-4">
							<div class="text-base font-semibold text-text">
								Threshold suggestion for {suggestion.stepper}
							</div>
							<div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
								<span class="text-text-muted">Unloaded floor:</span>
								<span class="text-text">{suggestion.unloaded_floor ?? '—'}</span>
								<span class="text-text-muted">Loaded dip:</span>
								<span class="text-text">{suggestion.loaded_dip ?? '—'}</span>
								<span class="text-text-muted">→ Trigger ≤:</span>
								<span class="text-text">{suggestion.trigger_level ?? '—'}</span>
								<span class="text-text-muted">Cruise TSTEP:</span>
								<span class="text-text">{suggestion.cruise_tstep}</span>
							</div>
							<div class="mt-1 text-sm text-text-muted">
								Geometric midpoint of the measured gap, from the latest unloaded + loaded test for this
								motor.
							</div>
							{#if !suggestion.enough_data}
								<Alert variant="warning">{suggestion.detail}</Alert>
							{/if}
							{#if suggestion.suggested_sgthrs != null}
								<div class="mt-3">
									<Button
										variant={suggestion.enough_data ? 'secondary' : 'ghost'}
										onclick={saveThreshold}
										loading={savingThreshold}
									>
										Save{suggestion.enough_data ? '' : ' provisional'} SGTHRS={suggestion.suggested_sgthrs}
										to machine.toml
									</Button>
								</div>
							{/if}
						</div>
					{/if}
				{:else}
					<div class="text-sm text-text-muted">Select a run to view its load curve.</div>
				{/if}
			</SectionCard>
		</div>
	</div>
</div>

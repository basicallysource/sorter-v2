<script lang="ts">
	import { confirmDialog } from '$lib/confirm.svelte';
	import { getBackendHttpBase } from '$lib/backend';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Trash2 from '@lucide/svelte/icons/trash-2';
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
	let showTstep = $state(true);

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
		measured_cruise_tstep: number | null;
		unloaded_floor: number | null;
		loaded_dip: number | null;
		trigger_level: number | null;
		suggested_sgthrs: number | null;
		enough_data: boolean;
		reliable: boolean;
		realistic_floor: number | null;
		speed: number | null;
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

	async function loadSuggestion(motor: string, speed?: number | null) {
		suggestion = null;
		try {
			// Speed-match: the suggestion must only use runs at the SAME speed as the
			// run being viewed — SG floor/dip/baseline all shift with speed, so mixing
			// speeds produces a nonsense (and unstable) recommendation.
			const qs = speed != null ? `?speed=${speed}` : '';
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-suggestion${qs}`);
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
		if (run.stepper_name) loadSuggestion(run.stepper_name, run.params?.speed);
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
			else await loadSuggestion(swStepper, swSpeed);
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
		if (
			!(await confirmDialog({
				title: 'Delete the run?',
				message: `Delete run ${run.id.slice(0, 8)} and its samples?`,
				action: 'Delete the run',
				danger: true
			}))
		)
			return;
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
	const stepperOptions = STEPPERS.map((s) => ({ value: s, label: s }));
	const directionOptions: { value: 'cw' | 'ccw'; label: string }[] = [
		{ value: 'cw', label: 'Clockwise' },
		{ value: 'ccw', label: 'Counterclockwise' }
	];
	const profileOptions: { value: Profile; label: string }[] = [
		{ value: 'constant', label: 'Constant spin' },
		{ value: 'chute_random', label: 'Chute: random go-to-angle' },
		{ value: 'pulsed', label: 'Pulsed with jitter' }
	];
</script>

<svelte:head><title>Sorter - StallGuard</title></svelte:head>

<svelte:window onkeydown={onKeydown} />

<div class="flex flex-col gap-(--gap-panels)">
	<PageHeader
		title="StallGuard"
		description="Record the TMC2209 load (SG_RESULT) of each motor. Run a sweep, read the load curve, and write a stall threshold to the machine config."
	/>

	{#if error}<Alert tone="danger">{error}</Alert>{/if}
	{#if notice}<Alert tone="success">{notice}</Alert>{/if}

	<Panel title="Each motor" description="Every SG_RESULT sample recorded, by motor." flush>
		{#if summary.length === 0}
			<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">Nothing recorded yet. Run a sweep below.</p>
		{:else}
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr>
							<th>Motor</th><th class="num">Samples</th><th class="num">SG min</th>
							<th class="num">SG mean</th><th class="num">SG max</th><th>Last seen</th>
						</tr>
					</thead>
					<tbody>
						{#each summary as row (row.stepper_name)}
							<tr>
								<td class="font-mono">{row.stepper_name}</td>
								<td class="num">{row.samples}</td>
								<td class="num">{row.sg_min}</td>
								<td class="num">{Math.round(row.sg_mean)}</td>
								<td class="num">{row.sg_max}</td>
								<td class="text-ink-muted">{fmtTime(row.last_seen)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</Panel>

	<Panel
		title="Run a sweep"
		description="Drives one motor through a representative motion and records its load curve. For a deliberate stall test, choose Loaded and hold the motor back by hand while it runs."
	>
		<div class="flex flex-col gap-4">
			<Alert tone="warning">
				This moves a real motor. Keep the area clear and your hand near the stop control.
			</Alert>
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
				<Field label="Motor" for="sw-stepper">
					<Select
						id="sw-stepper"
						bind:value={swStepper}
						options={stepperOptions}
						onchange={onStepperChange}
					/>
				</Field>
				<Field label="Motion" for="sw-profile">
					<Select id="sw-profile" bind:value={swProfile} options={profileOptions} />
				</Field>
				<Field label="Direction" for="sw-direction">
					<Select id="sw-direction" bind:value={swDirection} options={directionOptions} />
				</Field>
				<Field label="Speed" for="sw-speed">
					<Input id="sw-speed" type="number" unit="µsteps/s" bind:value={swSpeed} />
				</Field>
				<Field label="Duration" for="sw-duration">
					<Input id="sw-duration" type="number" unit="s" bind:value={swDuration} />
				</Field>
				<Field label="Label" for="sw-label" help="Optional.">
					<Input id="sw-label" bind:value={swLabel} />
				</Field>
				{#if swProfile === 'chute_random'}
					<Field label="Min angle" for="sw-min">
						<Input id="sw-min" type="number" unit="° output" bind:value={swChuteMinDeg} />
					</Field>
					<Field label="Max angle" for="sw-max">
						<Input id="sw-max" type="number" unit="° output" bind:value={swChuteMaxDeg} />
					</Field>
					<Field label="Min angle change" for="sw-delta">
						<Input id="sw-delta" type="number" unit="°" bind:value={swMinDeltaDeg} />
					</Field>
					<p class="text-sm text-ink-muted sm:col-span-2 lg:col-span-3">
						Random go-to-angle between the min and max output angle (clamped to the chute's safe
						travel, 345° at most), turning straight back on each arrival. Homes the chute first if
						needed, so it moves on absolute angles and can never reach an endstop.
					</p>
				{:else if swProfile === 'pulsed'}
					<Field label="Pulse size" for="sw-pulse">
						<Input id="sw-pulse" type="number" unit="° motor" bind:value={swPulseDeg} />
					</Field>
					<Field label="Dwell" for="sw-dwell">
						<Input id="sw-dwell" type="number" unit="ms" bind:value={swDwellMs} />
					</Field>
					<Field label="Jitter every" for="sw-jitter" help="0 turns the jitter off.">
						<Input id="sw-jitter" type="number" unit="pulses" bind:value={swJitterEvery} />
					</Field>
					<p class="text-sm text-ink-muted sm:col-span-2 lg:col-span-3">
						Separate pulses with a dwell between them, as the rotors and carousel really run, and an
						unstick jitter every few pulses. Only the moving phases are sampled.
					</p>
				{/if}
				<Field
					label="Cruise TSTEP"
					for="sw-tstep"
					help="Only motion at cruise (TSTEP at or below this; lower is faster) sets the threshold, since speeding up, slowing down and reversing dip SG even unloaded. Stays in StealthChop, where the TMC2209's StallGuard works. The chute cruises at TSTEP 75 to 150; this is saved as the velocity floor, so DIAG only acts at cruise."
				>
					<Input id="sw-tstep" type="number" bind:value={swCruiseTstep} />
				</Field>
			</div>
		</div>
		{#snippet footer()}
			<div class="mr-auto flex flex-wrap gap-x-5 gap-y-2">
				<Checkbox bind:checked={swLoaded}>Loaded (stall test)</Checkbox>
				<Checkbox bind:checked={swEnterToRun}>Enter runs a sweep</Checkbox>
			</div>
			<Button variant="primary" onclick={runSweep} loading={running}>Run sweep</Button>
		{/snippet}
	</Panel>

	<div class="grid grid-cols-1 gap-(--gap-panels) lg:grid-cols-3">
		<Panel title="Runs" description="Recent recordings." flush>
			{#if runs.length === 0}
				<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">No runs yet.</p>
			{:else}
				<ul class="max-h-[28rem] divide-y divide-line overflow-y-auto">
					{#each runs as run (run.id)}
						<li class="flex items-start gap-2 pr-2 {selectedRun?.id === run.id ? 'bg-primary-soft' : 'hover:bg-hover'}">
							<button
								type="button"
								onclick={() => selectRun(run)}
								class="flex min-w-0 flex-1 flex-col gap-0.5 py-(--pad-row) pl-(--pad-panel) text-left text-sm"
							>
								<span class="flex items-center justify-between gap-2">
									<span class="font-mono text-ink">{run.stepper_name ?? '–'}</span>
									<span class="text-ink-muted">{run.source}</span>
								</span>
								<span class="text-ink-muted">{fmtTime(run.started_at)}</span>
								<span class="text-ink-muted">
									{run.sample_count} samples{#if run.sg_min != null}, SG {run.sg_min} to {run.sg_max}{/if}{#if run.suggested_sgthrs != null}, SGTHRS {run.suggested_sgthrs}{/if}
									{#if run.label}<span class="text-ink"> · {run.label}</span>{/if}
								</span>
							</button>
							<Button
								variant="ghost"
								size="sm"
								icon={Trash2}
								label="Delete run"
								class="mt-2"
								onclick={(e: MouseEvent) => deleteRun(run, e)}
							/>
						</li>
					{/each}
				</ul>
			{/if}
		</Panel>

		<Panel
			title="Load curve"
			description="SG_RESULT over time. Lower means more load; a stall drops it toward 0."
			class="lg:col-span-2"
		>
			{#if selectedRun}
				{@const params = selectedRun.params ?? {}}
				<div class="flex flex-col gap-4">
					{@render facts([
						['Motor', selectedRun.stepper_name ?? '–'],
						['Speed', `${params.speed ?? '–'} µsteps/s`],
						['Direction', params.direction ?? '–'],
						['Duration', `${params.duration_s ?? '–'} s`],
						...(selectedRun.sg_mean != null ? [['Mean SG', Math.round(selectedRun.sg_mean)] as [string, number]] : []),
						...(selectedRun.suggested_sgthrs != null
							? [['Suggested SGTHRS', `${selectedRun.suggested_sgthrs} (trigger at or below ${triggerLevel})`] as [string, string]]
							: []),
						['IRUN', params.irun ?? '–'],
						['Acceleration', `${params.acceleration ?? '–'} µsteps/s²`],
						['Microsteps', params.microsteps ?? '–'],
						['Chopper', params.stealthchop == null ? '–' : params.stealthchop ? 'StealthChop' : 'SpreadCycle'],
						['Loaded', params.loaded ? 'Yes' : 'No'],
						['Cruise TSTEP', params.cruise_tstep ?? '–']
					])}
					<div class="flex flex-wrap gap-x-5 gap-y-2">
						<Checkbox bind:checked={showCs}>CS_ACTUAL</Checkbox>
						<Checkbox bind:checked={showTstep}>TSTEP</Checkbox>
					</div>
					{#if loadingSamples}
						<p class="text-sm text-ink-muted">Loading samples…</p>
					{:else}
						<div class="rounded-control bg-well p-3">
							<StallGuardChart
								{points}
								{triggerLevel}
								sgMean={selectedRun.sg_mean}
								cruiseTstep={params.cruise_tstep ?? null}
								{showCs}
								{showTstep}
							/>
						</div>
					{/if}
					{#if suggestion}
						<section class="flex flex-col gap-3 rounded-control bg-well p-4">
							<h3 class="text-base font-semibold text-ink">
								Threshold suggestion for {suggestion.stepper}
							</h3>
							{@render facts([
								['Unloaded floor', suggestion.unloaded_floor ?? '–'],
								['Loaded dip', suggestion.loaded_dip ?? '–'],
								['Trigger at or below', suggestion.trigger_level ?? '–'],
								['SGTHRS', suggestion.suggested_sgthrs ?? '–'],
								['Measured cruise TSTEP', suggestion.measured_cruise_tstep ?? '–'],
								['Gate TCOOLTHRS', suggestion.cruise_tstep],
								['Real-motion floor', suggestion.realistic_floor ?? '–']
							])}
							<p class="text-sm text-ink-muted">
								SGTHRS is the geometric midpoint of the gap between the measured floor and dip.
								TCOOLTHRS is the measured cruise TSTEP (the fastest sustained) times 1.75, so the gate
								stays open through cruise and off while speeding up or slowing down. Save writes both
								to machine.toml; nothing is assumed.
							</p>
							{#if suggestion.enough_data && !suggestion.reliable}
								<!-- Computable, but the data says it won't work here: a hard stop, not a nudge. -->
								<Alert
									tone="danger"
									title="Not reliably tunable{suggestion.speed ? ` at ${suggestion.speed} µsteps/s` : ''}"
								>
									{suggestion.detail}
								</Alert>
							{:else if !suggestion.enough_data}
								<Alert tone="warning">{suggestion.detail}</Alert>
							{/if}
							{#if suggestion.suggested_sgthrs != null}
								{@const safe = suggestion.enough_data && suggestion.reliable}
								<div>
									<Button
										variant={safe ? 'secondary' : 'ghost'}
										onclick={saveThreshold}
										loading={savingThreshold}
									>
										{safe ? 'Save' : 'Save anyway (unreliable)'} SGTHRS {suggestion.suggested_sgthrs} and
										TCOOLTHRS {suggestion.cruise_tstep} to machine.toml
									</Button>
								</div>
							{/if}
						</section>
					{/if}
				</div>
			{:else}
				<p class="text-sm text-ink-muted">Choose a run to see its load curve.</p>
			{/if}
		</Panel>
	</div>
</div>

{#snippet facts(items: [string, string | number][])}
	<dl class="flex flex-wrap gap-x-5 gap-y-1 text-sm">
		{#each items as [key, value] (key)}
			<div class="flex gap-1.5"><dt class="text-ink-muted">{key}</dt><dd class="text-ink">{value}</dd></div>
		{/each}
	</dl>
{/snippet}

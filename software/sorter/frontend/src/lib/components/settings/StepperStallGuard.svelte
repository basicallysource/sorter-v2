<!--
	One motor's StallGuard tab: a guided tuning in numbered steps, the load curve
	of a recording, the motor's stall settings, and the expert tools behind the
	steps. It is the body of the StallGuard tab of the chute and of the
	classification channel; each passes its own motor.

	The steps know where the person is from what the machine has recorded, not
	from what was clicked: a step is done when its recording exists at the speed
	being tuned, so a reload, or another browser, finds the same step open.
-->
<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import { confirmDialog } from '$lib/confirm.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import {
		autoCruiseTstep,
		defaultSweepOptions,
		fmtTime,
		motionSentence,
		replay,
		speedAtTstep,
		tstepAtSpeed,
		type ChartPoint,
		type Replay,
		type Run,
		type Sample,
		type Suggestion,
		type SummaryRow
	} from '$lib/settings/stallguard';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Disclosure from '$lib/components/ui/Disclosure.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import Step from '$lib/components/ui/Step.svelte';
	import StepperStallGuardCurve from './stepper/StepperStallGuardCurve.svelte';
	import StepperStallGuardRuns from './stepper/StepperStallGuardRuns.svelte';
	import StepperStallGuardSettings from './stepper/StepperStallGuardSettings.svelte';
	import StepperStallGuardSweepOptions from './stepper/StepperStallGuardSweepOptions.svelte';

	let {
		motor,
		label,
		operatingSpeedEndpoint = undefined,
		stressTestHref = undefined
	}: {
		// The motor's name in the API: 'chute', 'carousel'.
		motor: string;
		// What the page calls it, in a sentence.
		label: string;
		// Where the motor's operating speed is kept, when it has one (the
		// chute's): the tuning starts from it.
		operatingSpeedEndpoint?: string;
		// Where the motor has a stress test that runs with detection armed.
		stressTestHref?: string;
	} = $props();

	const manager = getMachinesContext();
	const Label = $derived(label.charAt(0).toUpperCase() + label.slice(1));

	function base(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	async function readError(res: Response): Promise<string> {
		const body = await res.json().catch(() => ({}));
		return typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`;
	}

	// --- Stall detection settings ---
	let sgEnabled = $state(false);
	let sgThrs = $state(50);
	let sgTcoolthrs = $state(150);
	let microsteps = $state(8);
	// What the machine runs on: as read from the driver, or as last saved. The
	// fields above can hold an edit that is not saved yet.
	let applied = $state<{ enabled: boolean; sgthrs: number; tcoolthrs: number } | null>(null);
	let settingsLoading = $state(true);
	// Only read settings are shown and saved, so a failed read never saves the defaults.
	let settingsLoaded = $state(false);
	let settingsAttempted = $state(false);
	let settingsSaving = $state(false);
	let settingsError = $state<string | null>(null);
	let settingsNotice = $state('');

	async function loadSettings() {
		settingsLoading = true;
		settingsError = null;
		try {
			const res = await fetch(`${base()}/api/stepper/${motor}/tmc`);
			if (!res.ok) throw new Error(await readError(res));
			const data = await res.json();
			if (typeof data.microsteps === 'number') microsteps = data.microsteps;
			if (data.stallguard) {
				sgEnabled = !!data.stallguard.enabled;
				if (typeof data.stallguard.sgthrs === 'number') sgThrs = data.stallguard.sgthrs;
				if (typeof data.stallguard.tcoolthrs === 'number') sgTcoolthrs = data.stallguard.tcoolthrs;
				applied = { enabled: sgEnabled, sgthrs: sgThrs, tcoolthrs: sgTcoolthrs };
			}
			if (operatingSpeedEndpoint) {
				const speedRes = await fetch(`${base()}${operatingSpeedEndpoint}`);
				if (speedRes.ok) {
					const speed = Number((await speedRes.json())?.operating_speed_microsteps_per_second);
					operatingSpeed = Number.isFinite(speed) && speed > 0 ? speed : null;
					if (operatingSpeed !== null && !speedTouched) swSpeed = operatingSpeed;
				}
			}
			settingsLoaded = true;
		} catch (e: any) {
			settingsError = e.message ?? 'Failed to read the stall detection settings';
		} finally {
			settingsLoading = false;
			settingsAttempted = true;
		}
	}

	async function saveSettings() {
		settingsSaving = true;
		settingsError = null;
		settingsNotice = '';
		try {
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-config`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ sgthrs: sgThrs, tcoolthrs: sgTcoolthrs, enabled: sgEnabled })
			});
			if (!res.ok) throw new Error(await readError(res));
			const data = await res.json();
			sgEnabled = !!data.enabled;
			sgThrs = data.sgthrs;
			sgTcoolthrs = data.tcoolthrs;
			applied = { enabled: sgEnabled, sgthrs: sgThrs, tcoolthrs: sgTcoolthrs };
			check = null;
			settingsNotice = data.applied_live
				? 'Stall detection saved.'
				: 'Stall detection saved. It applies at the next start.';
		} catch (e: any) {
			settingsError = e.message ?? 'Failed to save the stall detection settings';
		} finally {
			settingsSaving = false;
		}
	}

	// --- The speed being tuned ---
	// The speed the motor really runs at, where the page knows it (the chute's
	// operating speed). The field starts there; a motor that has none starts at 1500.
	let operatingSpeed = $state<number | null>(null);
	let swSpeed = $state<number | null>(1500);
	let speedTouched = $state(false);
	let options = $state(untrack(() => defaultSweepOptions(motor)));

	const speedError = $derived(
		swSpeed === null || !(swSpeed > 0) ? 'Enter a speed above 0.' : undefined
	);
	const tuneSpeed = $derived(speedError || swSpeed === null ? null : Math.round(swSpeed));
	const speedText = $derived(tuneSpeed === null ? '–' : tuneSpeed.toLocaleString());
	// A negative speed is counterclockwise, which is how a recording keeps it.
	const signedTuneSpeed = $derived(
		tuneSpeed === null ? null : options.direction === 'cw' ? tuneSpeed : -tuneSpeed
	);
	const atOperatingSpeed = $derived(operatingSpeed !== null && tuneSpeed === operatingSpeed);
	// The TSTEP the motor cruises at, and whether the driver would look for a stall there.
	const cruiseTstep = $derived(tuneSpeed === null ? null : tstepAtSpeed(tuneSpeed, microsteps));
	const autoCruise = $derived(autoCruiseTstep(tuneSpeed, microsteps));
	const cruiseParam = $derived(
		options.cruiseTstep !== null && options.cruiseTstep > 0
			? Math.round(options.cruiseTstep)
			: autoCruise
	);
	const verdict = $derived.by(() => {
		if (cruiseTstep === null || applied === null) return null;
		if (cruiseTstep > applied.tcoolthrs) return 'blind' as const;
		return applied.enabled ? ('ready' as const) : ('off' as const);
	});

	function useOperatingSpeed() {
		swSpeed = operatingSpeed;
		speedTouched = true;
	}

	// --- What the machine has recorded ---
	let runs = $state<Run[]>([]);
	let summary = $state<SummaryRow[]>([]);
	let selectedRun = $state<Run | null>(null);
	let points = $state<ChartPoint[]>([]);
	let loadingSamples = $state(false);
	// The threshold suggestion for the speed of the recording on show.
	let suggestion = $state<Suggestion | null>(null);
	let error = $state<string | null>(null);
	let curveElement = $state<HTMLElement>();
	const motorSummary = $derived(summary.find((row) => row.stepper_name === motor));

	async function loadRuns() {
		try {
			const res = await fetch(`${base()}/api/stepper-telemetry/runs?limit=200&stepper=${motor}`);
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

	// The suggestion must only use recordings at the SAME speed as the one on
	// show: the floor, the dip and the baseline all shift with speed, so mixing
	// speeds gives a nonsense (and unstable) recommendation. The same call, for
	// the speed being tuned, is what tells the steps which recordings exist.
	async function readSuggestion(speed: number | null | undefined): Promise<Suggestion | null> {
		try {
			const qs = speed != null ? `?speed=${speed}` : '';
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-suggestion${qs}`);
			return res.ok ? ((await res.json()) as Suggestion) : null;
		} catch {
			return null;
		}
	}

	let suggestionSeq = 0;
	async function loadSuggestion(speed: number | null | undefined) {
		const seq = ++suggestionSeq;
		suggestion = null;
		const next = await readSuggestion(speed);
		if (seq === suggestionSeq) suggestion = next;
	}

	let selectSeq = 0;
	async function selectRun(run: Run) {
		const seq = ++selectSeq;
		selectedRun = run;
		loadingSamples = true;
		points = [];
		error = null;
		void loadSuggestion(run.params?.speed);
		try {
			const res = await fetch(`${base()}/api/stepper-telemetry/runs/${run.id}/samples`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			if (seq !== selectSeq) return;
			const rows = data.samples as any[];
			const t0 = rows.length ? rows[0].recorded_at : 0;
			points = rows.map((r) => ({
				x: r.recorded_at - t0,
				sg: r.sg_result,
				cs: r.cs_actual,
				tstep: r.tstep
			}));
		} catch (e: any) {
			if (seq === selectSeq) error = e.message ?? 'Failed to load samples';
		} finally {
			if (seq === selectSeq) loadingSamples = false;
		}
	}

	// A row of the list chooses a recording up in the load curve, so bring it into view.
	async function pickRun(run: Run) {
		await selectRun(run);
		curveElement?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
	}

	async function deleteRun(run: Run) {
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
				method: 'DELETE'
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			await Promise.all([loadRuns(), loadSummary(), loadTuning()]);
			if (selectedRun?.id === run.id) {
				selectedRun = null;
				points = [];
				suggestion = null;
				if (runs.length > 0) await selectRun(runs[0]);
			}
		} catch (e: any) {
			error = e.message ?? 'Failed to delete run';
		}
	}

	// --- The tuning at the speed being tuned ---
	// The suggestion for that speed: how many recordings there are at it, what
	// they read, and the settings they give. It is re-read when the speed changes
	// and after every recording.
	let tuning = $state<Suggestion | null>(null);
	let tuningFor = $state<number | null>(null);
	let tuningLoaded = $state(false);
	let tuningSeq = 0;

	async function loadTuning() {
		const speed = signedTuneSpeed;
		if (speed === null) return;
		const seq = ++tuningSeq;
		const next = await readSuggestion(speed);
		if (seq !== tuningSeq) return;
		tuning = next;
		tuningFor = next ? speed : null;
		tuningLoaded = true;
		if (!next) error = 'Failed to read the recordings made at this speed';
	}

	$effect(() => {
		const speed = signedTuneSpeed;
		if (settingsLoading || speed === null) return;
		const handle = setTimeout(() => untrack(() => void loadTuning()), 250);
		return () => clearTimeout(handle);
	});

	const plan = $derived(tuningFor !== null && tuningFor === signedTuneSpeed ? tuning : null);

	// --- The steps ---
	// The speed is confirmed in the first step. Recordings at the speed also count,
	// but not while the person has been changing it: the step does not fold away
	// under their hands.
	let speedConfirmed = $state(false);
	// The speed the settings were saved for in step 4, and the check made after.
	let savedFor = $state<number | null>(null);
	let check = $state<{ speed: number; sgthrs: number; tcoolthrs: number; result: Replay } | null>(
		null
	);
	// A step the person opened again, over the one that is next.
	let openStep = $state<number | null>(null);

	const haveFree = $derived(plan !== null && plan.unloaded_floor !== null);
	const haveStall = $derived(plan !== null && plan.loaded_dip !== null);
	const matchesSaved = $derived(
		plan !== null &&
			applied !== null &&
			applied.enabled &&
			plan.suggested_sgthrs !== null &&
			applied.sgthrs === plan.suggested_sgthrs &&
			applied.tcoolthrs === plan.cruise_tstep
	);
	const checkHere = $derived(check !== null && check.speed === signedTuneSpeed ? check : null);
	const checkTripped = $derived(checkHere !== null && checkHere.result.tripped > 0);
	const done = $derived.by(() => {
		const s1 = tuneSpeed !== null && (speedConfirmed || (!speedTouched && (haveFree || haveStall)));
		const s2 = s1 && haveFree;
		const s3 = s2 && haveStall;
		const s4 = s3 && ((savedFor !== null && savedFor === signedTuneSpeed) || matchesSaved);
		const s5 = s4 && checkHere !== null && checkHere.result.looked > 0 && !checkTripped;
		return [s1, s2, s3, s4, s5];
	});
	const currentStep = $derived(done.indexOf(false) === -1 ? 5 : done.indexOf(false) + 1);

	function statusOf(n: number): 'done' | 'current' | 'locked' {
		return done[n - 1] ? 'done' : n === currentStep ? 'current' : 'locked';
	}
	// The one step that shows its body: the one the person opened again, else the next to do.
	const openNow = $derived(
		openStep !== null && statusOf(openStep) !== 'locked'
			? openStep
			: done[currentStep - 1]
				? null
				: currentStep
	);

	function confirmSpeed() {
		speedConfirmed = true;
		openStep = null;
	}

	// --- Recording ---
	type Recording = 'free' | 'stall' | 'check';
	const STEP_OF: Record<Recording, number> = { free: 2, stall: 3, check: 5 };
	const RECORDING_AT: Record<number, Recording> = { 2: 'free', 3: 'stall', 5: 'check' };
	const RECORDING_LABEL: Record<Recording, string> = {
		free: 'Free running',
		stall: 'Stall',
		check: 'Check'
	};
	let running = $state<Recording | null>(null);
	let runError = $state<{ step: number; message: string } | null>(null);

	async function record(kind: Recording) {
		if (running || tuneSpeed === null) return;
		const checking = kind === 'check' ? applied : null;
		if (kind === 'check' && !checking) return;
		running = kind;
		runError = null;
		speedConfirmed = true;
		try {
			const duration = Number(options.duration);
			if (!(duration > 0)) throw new Error('The recording needs a duration above 0 seconds.');
			const qs = new URLSearchParams({
				stepper: motor,
				speed: String(tuneSpeed),
				direction: options.direction,
				duration_s: String(duration),
				loaded: String(kind === 'stall'),
				profile: options.profile,
				cruise_tstep: String(cruiseParam)
			});
			if (options.profile === 'chute_random') {
				qs.set('chute_min_deg', String(options.chuteMinDeg));
				qs.set('chute_max_deg', String(options.chuteMaxDeg));
				qs.set('min_delta_deg', String(options.minDeltaDeg));
			} else if (options.profile === 'pulsed') {
				qs.set('pulse_deg', String(options.pulseDeg));
				qs.set('dwell_ms', String(options.dwellMs));
				qs.set('jitter_every', String(options.jitterEvery));
			}
			qs.set('label', options.label.trim() || RECORDING_LABEL[kind]);
			const res = await fetch(`${base()}/stepper/stallguard-sweep?${qs}`, { method: 'POST' });
			if (!res.ok) throw new Error(await readError(res));
			const data = await res.json();
			if (checking && signedTuneSpeed !== null) {
				// A sweep keeps stall detection off while it runs, so the check asks what
				// the saved settings would have done to what it recorded.
				check = {
					speed: signedTuneSpeed,
					sgthrs: checking.sgthrs,
					tcoolthrs: checking.tcoolthrs,
					result: replay((data.samples ?? []) as Sample[], checking.sgthrs, checking.tcoolthrs)
				};
			}
			await Promise.all([loadRuns(), loadSummary(), loadTuning()]);
			const fresh = runs.find((r) => r.id === data.run_id);
			if (fresh) await selectRun(fresh);
			openStep = null;
		} catch (e: any) {
			runError = { step: STEP_OF[kind], message: e.message ?? 'The recording failed' };
		} finally {
			running = null;
		}
	}

	function onKeydown(ev: KeyboardEvent) {
		if (!options.enterToRun || ev.key !== 'Enter' || running) return;
		const kind = RECORDING_AT[openNow ?? 0];
		if (!kind) return;
		ev.preventDefault();
		void record(kind);
	}

	let sweepOptionsOpen = $state(false);
	async function openSweepOptions() {
		sweepOptionsOpen = true;
		await tick();
		document
			.getElementById('sg-sweep-options')
			?.scrollIntoView({ behavior: 'smooth', block: 'center' });
	}

	// --- Saving the suggestion (step 4) ---
	let saving = $state(false);
	let saveError = $state<string | null>(null);

	async function saveThreshold() {
		if (!plan || plan.suggested_sgthrs === null) return;
		saving = true;
		saveError = null;
		try {
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-config`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					sgthrs: plan.suggested_sgthrs,
					// The speed floor is the cruise TSTEP the recordings measured, with a
					// margin, so the driver only looks while the motor cruises (where the
					// threshold was tuned).
					tcoolthrs: plan.cruise_tstep,
					enabled: true
				})
			});
			if (!res.ok) throw new Error(await readError(res));
			const data = await res.json();
			// The stall detection settings now hold what was saved.
			sgEnabled = !!data.enabled;
			sgThrs = data.sgthrs;
			sgTcoolthrs = data.tcoolthrs;
			applied = { enabled: sgEnabled, sgthrs: sgThrs, tcoolthrs: sgTcoolthrs };
			savedFor = signedTuneSpeed;
			check = null;
			settingsNotice = '';
			openStep = null;
		} catch (e: any) {
			saveError = e.message ?? 'Failed to save the settings';
		} finally {
			saving = false;
		}
	}

	onMount(() => {
		void loadSettings();
		void (async () => {
			await Promise.all([loadRuns(), loadSummary()]);
			// The latest recording is on show from the start.
			if (!selectedRun && runs.length > 0) await selectRun(runs[0]);
		})();
	});

	const ready = $derived(settingsAttempted && tuningLoaded);
</script>

<svelte:window onkeydown={onKeydown} />

<div class="flex min-w-0 flex-col gap-(--gap-panels)">
	{#if error}<Alert tone="danger">{error}</Alert>{/if}

	<Panel
		title="Tune StallGuard"
		description="StallGuard reads how hard {label} is working: high when it turns freely, near 0 when it stalls. Tuning finds the line between the two, at the speed it really runs."
		flush
	>
		{#snippet actions()}
			{#if checkTripped}
				<Badge tone="warning">It would trip</Badge>
			{:else if done[3]}
				<Badge tone="success">Tuned</Badge>
			{:else}
				<Badge tone="primary">Step {currentStep} of 5</Badge>
			{/if}
		{/snippet}
		{#if !ready}
			<div
				class="flex items-center gap-2 border-t border-line px-(--pad-panel) py-4 text-sm text-ink-muted"
			>
				<Spinner size={14} /> Reading the driver and your recordings
			</div>
		{:else}
			<ol class="divide-y divide-line border-t border-line">
				<Step
					n={1}
					title="Check the speed"
					status={statusOf(1)}
					open={openNow === 1}
					hint={statusOf(1) === 'done'
						? `${speedText} µsteps/s at 1/${microsteps} microstepping`
						: undefined}
				>
					{#snippet actions()}
						{#if statusOf(1) === 'done' && verdict === 'blind'}
							<Badge tone="warning">Can't trip yet</Badge>
						{/if}
						{@render reopen(1, 'Change')}
					{/snippet}
					<div class="flex max-w-2xl flex-col gap-4">
						<p class="text-sm text-ink">
							StallGuard's readings change with speed, so it is tuned at the one speed {label} really
							runs at.
							{#if operatingSpeed !== null}
								The speed below is its operating speed as currently set.
							{:else}
								Type the speed it runs at.
							{/if}
						</p>
						{#if settingsError}
							<Alert tone="danger" actions={settingsLoaded ? undefined : tryAgain}>
								{settingsError}
							</Alert>
						{/if}
						<Field label="Speed" for="sg-speed" error={speedError}>
							<div class="flex flex-wrap items-center gap-3">
								<Input
									id="sg-speed"
									type="number"
									step={100}
									unit="µsteps/s"
									bind:value={swSpeed}
									oninput={() => (speedTouched = true)}
									invalid={!!speedError}
									class="w-56"
								/>
								{#if atOperatingSpeed}
									<Badge tone="primary">Operating speed</Badge>
								{:else if operatingSpeed !== null}
									<Button variant="ghost" size="sm" icon={RotateCcw} onclick={useOperatingSpeed}>
										Use the operating speed, {operatingSpeed.toLocaleString()}
									</Button>
								{/if}
							</div>
						</Field>
						{#if verdict === 'blind' && applied && cruiseTstep !== null}
							<Alert tone="warning" title="StallGuard can't trip at this speed yet">
								At {speedText} µsteps/s and 1/{microsteps} microstepping {label} cruises at TSTEP {cruiseTstep},
								slower than the speed floor of {applied.tcoolthrs.toLocaleString()}, so the driver
								never checks for a stall. Steps 2 to 4 measure it and set a speed floor that fits.
							</Alert>
						{:else if verdict === 'off' && applied && cruiseTstep !== null}
							<Alert tone="info" title="StallGuard is off">
								At {speedText} µsteps/s {label} cruises at TSTEP {cruiseTstep}, inside the speed
								floor of {applied.tcoolthrs.toLocaleString()}, so the driver would check for a
								stall, but detection is switched off. Step 4 turns it on.
							</Alert>
						{:else if verdict === 'ready' && applied && cruiseTstep !== null}
							<Alert tone="success" title="StallGuard can trip at this speed">
								At {speedText} µsteps/s and 1/{microsteps} microstepping {label} cruises at TSTEP {cruiseTstep},
								inside the speed floor of {applied.tcoolthrs.toLocaleString()}. The next steps tune
								the threshold for this speed.
							</Alert>
						{/if}
						<div>
							<Button variant="primary" disabled={tuneSpeed === null} onclick={confirmSpeed}>
								Tune at {speedText} µsteps/s
							</Button>
						</div>
					</div>
				</Step>

				<Step
					n={2}
					title="Record {label} running freely"
					status={statusOf(2)}
					open={openNow === 2}
					hint={statusOf(2) === 'done' && plan
						? `Running freely it reads ${plan.unloaded_floor} or higher.`
						: statusOf(2) === 'locked'
							? 'Check the speed first.'
							: undefined}
				>
					{#snippet actions()}
						{@render reopen(2, 'Record again')}
					{/snippet}
					<div class="flex max-w-2xl flex-col gap-4">
						<p class="text-sm text-ink">
							{Label} runs a short move at {speedText} µsteps/s with nothing holding it back, and StallGuard
							records how hard it works. This is what normal running looks like, and a stall has to read
							well below it.
						</p>
						{@render motion()}
						<Alert tone="warning">
							This moves a real motor. Keep the area clear and your hand near the stop control.
						</Alert>
						{#if plan && plan.unloaded_runs > 0 && !haveFree}
							<Alert tone="warning" title="The last recording could not be used">
								{plan.detail}
							</Alert>
						{/if}
						{@render failure(2)}
						<div class="flex flex-wrap items-center gap-3">
							<Button
								variant="primary"
								loading={running === 'free'}
								disabled={running !== null && running !== 'free'}
								onclick={() => record('free')}
							>
								Record it running freely
							</Button>
							{#if running === 'free'}
								<span class="text-sm text-ink-muted">
									Recording for about {options.duration} seconds. Keep clear of it.
								</span>
							{/if}
						</div>
					</div>
				</Step>

				<Step
					n={3}
					title="Record a stall"
					status={statusOf(3)}
					open={openNow === 3}
					hint={statusOf(3) === 'done' && plan
						? `Held back, it dips to ${plan.loaded_dip}.`
						: statusOf(3) === 'locked'
							? 'Record it running freely first.'
							: undefined}
				>
					{#snippet actions()}
						{@render reopen(3, 'Record again')}
					{/snippet}
					<div class="flex max-w-2xl flex-col gap-4">
						<p class="text-sm text-ink">
							Now the same move again, but you hold {label} back by hand so it stalls. This shows StallGuard
							what a stall reads, so it can tell one from normal running.
						</p>
						<p class="text-sm text-ink">
							Press the button, then hold the motor back as soon as it starts moving and keep
							holding until the recording ends, about {options.duration} seconds.
						</p>
						{@render motion()}
						<Alert tone="warning">
							This moves a real motor and you will be holding it. Hold only the part that turns,
							keep your fingers away from gears and the endstop, and let go if anything feels wrong.
						</Alert>
						{#if plan && plan.loaded_runs > 0 && !haveStall}
							<Alert tone="warning" title="The last recording could not be used">
								{plan.detail}
							</Alert>
						{/if}
						{@render failure(3)}
						<div class="flex flex-wrap items-center gap-3">
							<Button
								variant="primary"
								loading={running === 'stall'}
								disabled={running !== null && running !== 'stall'}
								onclick={() => record('stall')}
							>
								Record a stall
							</Button>
							{#if running === 'stall'}
								<span class="text-sm font-medium text-ink">
									Recording now. Hold the motor back until it stops.
								</span>
							{/if}
						</div>
					</div>
				</Step>

				<Step
					n={4}
					title="Review and save"
					status={statusOf(4)}
					open={openNow === 4}
					hint={statusOf(4) === 'done' && applied
						? `Saved: threshold ${applied.sgthrs}, speed floor ${applied.tcoolthrs}.`
						: statusOf(4) === 'locked'
							? 'Needs both recordings.'
							: undefined}
				>
					{#snippet actions()}
						{@render reopen(4, 'Review')}
					{/snippet}
					{#if plan && plan.suggested_sgthrs !== null && plan.trigger_level !== null}
						<div class="flex max-w-2xl flex-col gap-4">
							<p class="text-sm text-ink">
								StallGuard compared your two recordings and suggests these settings for {label} at {speedText}
								µsteps/s. The load curve below shows them.
							</p>
							<div
								class="grid grid-cols-1 divide-y divide-line rounded-control bg-well sm:grid-cols-2 sm:divide-x sm:divide-y-0"
							>
								<Stat
									label="Threshold (SGTHRS)"
									value={plan.suggested_sgthrs}
									hint={applied
										? applied.sgthrs === plan.suggested_sgthrs
											? 'Saved'
											: `Now ${applied.sgthrs}`
										: undefined}
								/>
								<Stat
									label="Speed floor (TCOOLTHRS)"
									value={plan.cruise_tstep}
									hint={applied
										? applied.tcoolthrs === plan.cruise_tstep
											? 'Saved'
											: `Now ${applied.tcoolthrs}`
										: undefined}
								/>
							</div>
							<p class="text-sm text-ink-muted">
								The threshold is the line between a free-running reading ({plan.unloaded_floor} or higher)
								and a stall ({plan.loaded_dip} or lower): StallGuard calls it a stall when the reading
								falls to {plan.trigger_level} or lower. The speed floor keeps it from judging while the
								motor speeds up or slows down: it only looks above about {speedAtTstep(
									plan.cruise_tstep,
									microsteps
								).toLocaleString()} µsteps/s.
							</p>
							{#if !plan.reliable}
								<Alert
									tone="danger"
									title="Not reliably tunable at {speedText} µsteps/s"
									actions={stallAgain}
								>
									{plan.detail}
								</Alert>
							{/if}
							{#if saveError}<Alert tone="danger">{saveError}</Alert>{/if}
							<div>
								<Button
									variant={plan.reliable ? 'primary' : 'ghost'}
									loading={saving}
									onclick={saveThreshold}
								>
									{plan.reliable ? 'Save and turn on StallGuard' : 'Save anyway (unreliable)'}
								</Button>
							</div>
						</div>
					{/if}
				</Step>

				<Step
					n={5}
					title="Check it"
					status={statusOf(5)}
					open={openNow === 5}
					hint={statusOf(5) === 'done'
						? 'Nothing would have tripped.'
						: statusOf(5) === 'locked'
							? 'Save the settings first.'
							: undefined}
				>
					{#snippet actions()}
						<Badge>Optional</Badge>
						{@render reopen(5, 'Record again')}
					{/snippet}
					<div class="flex max-w-2xl flex-col gap-4">
						<p class="text-sm text-ink">
							Record {label} running freely once more. StallGuard checks that recording against the settings
							you saved and tells you if it would have stopped the machine. Nothing should trip.
						</p>
						{@render motion()}
						<Alert tone="warning">
							This moves a real motor. Keep the area clear and your hand near the stop control.
						</Alert>
						{@render failure(5)}
						{#if checkHere}
							{@const r = checkHere.result}
							{#if r.looked === 0}
								<Alert tone="info" title="Nothing to check against">
									The motor never ran fast enough for StallGuard to look: TSTEP stayed above the
									speed floor of {checkHere.tcoolthrs}. Check the speed in step 1.
								</Alert>
							{:else if r.tripped === 0}
								<Alert tone="success" title="Nothing would have tripped">
									StallGuard would have looked at {r.looked} readings. The lowest was {r.lowest},
									above the trigger of {2 * checkHere.sgthrs}.
								</Alert>
							{:else}
								<Alert tone="danger" title="It would have stopped the machine">
									{r.tripped} of {r.looked} readings were at or under the trigger of {2 *
										checkHere.sgthrs}
									while running freely (the lowest was {r.lowest}), so it would have called a stall
									that was not one. Record the stall again and save, or lower the threshold under
									Stall detection below.
								</Alert>
							{/if}
						{/if}
						<div class="flex flex-wrap items-center gap-3">
							<Button
								variant="primary"
								loading={running === 'check'}
								disabled={(running !== null && running !== 'check') || applied === null}
								onclick={() => record('check')}
							>
								Record a check
							</Button>
							{#if running === 'check'}
								<span class="text-sm text-ink-muted">
									Recording for about {options.duration} seconds. Keep clear of it.
								</span>
							{/if}
						</div>
						{#if stressTestHref}
							<p class="text-sm text-ink-muted">
								A sweep keeps stall detection off while it runs. For a longer test with detection
								really on, the stress test runs {label} for a minute with the saved settings armed, and
								stops and says so if anything trips.
							</p>
							<div>
								<Button variant="ghost" size="sm" icon={ArrowRight} href={stressTestHref}>
									Open the stress test
								</Button>
							</div>
						{/if}
					</div>
				</Step>
			</ol>
		{/if}
	</Panel>

	{#if selectedRun}
		<div bind:this={curveElement}>
			<StepperStallGuardCurve
				{label}
				{runs}
				run={selectedRun}
				{points}
				loading={loadingSamples}
				{suggestion}
				onselect={selectRun}
			/>
		</div>
	{/if}

	<Panel
		title="Stall detection"
		description="Whether {label} halts the machine when it stalls, and how hard it must be loaded to count as one."
	>
		{#if settingsLoading}
			<div class="flex items-center gap-2 text-sm text-ink-muted">
				<Spinner size={14} /> Reading the driver
			</div>
		{:else}
			<div class="flex flex-col gap-4">
				{#if settingsError}
					<Alert tone="danger" actions={settingsLoaded ? undefined : tryAgain}>
						{settingsError}
					</Alert>
				{/if}
				{#if settingsLoaded}
					<StepperStallGuardSettings bind:sgEnabled bind:sgThrs bind:sgTcoolthrs {microsteps} />
				{/if}
			</div>
		{/if}
		{#snippet footer()}
			{#if settingsNotice && !settingsError}
				<p class="mr-auto min-w-0 text-sm text-ink-muted">{settingsNotice}</p>
			{/if}
			<Button
				variant="primary"
				loading={settingsSaving}
				disabled={!settingsLoaded}
				onclick={saveSettings}
			>
				Save
			</Button>
		{/snippet}
	</Panel>

	<Panel
		title="Expert tools"
		description="What the steps use, by hand: how a sweep moves, every past recording, and the readings behind them."
		flush
	>
		<div class="divide-y divide-line border-t border-line">
			<div id="sg-sweep-options">
				<Disclosure
					title="Sweep options"
					help="Motion, direction, duration, cruise TSTEP, angles"
					bind:open={sweepOptionsOpen}
				>
					<StepperStallGuardSweepOptions bind:options {motor} {autoCruise} />
				</Disclosure>
			</div>
			<Disclosure
				title="Past recordings"
				help={runs.length > 0 ? `${runs.length} in all, newest first` : 'None yet'}
			>
				<StepperStallGuardRuns
					{runs}
					selectedId={selectedRun?.id ?? null}
					onselect={pickRun}
					ondelete={deleteRun}
				/>
			</Disclosure>
			<Disclosure title="Recorded readings" help="Every SG_RESULT sample recorded for {label}">
				{#if motorSummary}
					<div class="grid grid-cols-2 divide-x divide-line sm:grid-cols-4">
						<Stat
							label="Samples"
							value={motorSummary.samples}
							hint="Last {fmtTime(motorSummary.last_seen)}"
						/>
						<Stat label="SG min" value={motorSummary.sg_min} />
						<Stat label="SG mean" value={Math.round(motorSummary.sg_mean)} />
						<Stat label="SG max" value={motorSummary.sg_max} />
					</div>
				{:else}
					<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">
						Nothing recorded yet. Step 2 makes the first recording.
					</p>
				{/if}
			</Disclosure>
		</div>
	</Panel>
</div>

{#snippet stallAgain()}
	<Button size="sm" onclick={() => (openStep = 3)}>Record the stall again</Button>
{/snippet}

{#snippet tryAgain()}
	<Button size="sm" loading={settingsLoading} onclick={loadSettings}>Try again</Button>
{/snippet}

<!-- What a done step offers: to be opened again, or, while it is, to be closed. -->
{#snippet reopen(n: number, text: string)}
	{#if openStep === n}
		<Button variant="ghost" size="sm" onclick={() => (openStep = null)}>Close</Button>
	{:else if statusOf(n) === 'done'}
		<Button variant="ghost" size="sm" onclick={() => (openStep = n)}>{text}</Button>
	{/if}
{/snippet}

<!-- What a recording will do, and the way to change it. -->
{#snippet motion()}
	<p class="text-sm text-ink-muted">
		{motionSentence(options)}
		<Button variant="ghost" size="sm" onclick={openSweepOptions}>Change how it moves</Button>
	</p>
{/snippet}

{#snippet failure(step: number)}
	{#if runError?.step === step}<Alert tone="danger">{runError.message}</Alert>{/if}
{/snippet}

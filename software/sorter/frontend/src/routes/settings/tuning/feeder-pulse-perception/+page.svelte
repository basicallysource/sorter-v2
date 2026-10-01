<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import Button from '$lib/components/ui/Button.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import TuningParamRow from '$lib/components/settings/TuningParamRow.svelte';
	import TuningPresets from '$lib/components/settings/TuningPresets.svelte';
	import SettingsSaveBar from '$lib/components/settings/SettingsSaveBar.svelte';
	import UnsavedChangesDialog from '$lib/components/settings/UnsavedChangesDialog.svelte';
	import { createUnsavedGuard } from '$lib/settings/unsavedChanges.svelte';
	import {
		groupTuningSections,
		type TuningFieldMeta,
		type TuningPreset,
		type TuningValues
	} from '$lib/settings/tuning';

	// Exit-pulse speed presets. The exit pulse is how hard C2/C3 meter a piece
	// off the edge into the next channel; bigger nudges = faster hand-off but a
	// higher chance of pushing two pieces through at once. Each preset only sets
	// the two exit-pulse fields (merged over the current form, not auto-saved).
	const exitPulsePresets: TuningPreset[] = [
		{
			label: 'Conservative (2°)',
			description:
				'Gentlest exit metering — 2° per pulse, 100 ms pause. Least chance of pushing two pieces into the classification channel at once; slowest hand-off. (Current default.)',
			values: { exit_pulse_output_deg: 2, exit_pulse_pause_ms: 100 }
		},
		{
			label: 'Balanced (4°)',
			description:
				'Middle ground — 4° per pulse, 100 ms pause. Faster exit hand-off with a modest double-feed risk.',
			values: { exit_pulse_output_deg: 4, exit_pulse_pause_ms: 100 }
		},
		{
			label: 'Aggressive (8°)',
			description:
				'Fastest exit metering — 8° per pulse, 100 ms pause. Highest throughput; most likely to push two pieces through together.',
			values: { exit_pulse_output_deg: 8, exit_pulse_pause_ms: 100 }
		}
	];

	let fields = $state<TuningFieldMeta[]>([]);
	let values = $state<TuningValues>({});
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);

	let sections = $derived(groupTuningSections(fields));

	// Guards navigation while the form differs from what is stored on the machine.
	// Armed only once load() has taken a snapshot, so it never fires on a page
	// that is still fetching.
	const guard = createUnsavedGuard({
		current: () => values,
		save,
		ready: () => !loading && !saving
	});

	type AutotuneParamMeta = {
		key: string;
		type: string;
		min: number;
		max: number;
		label: string;
	};
	type AutotuneTrial = {
		id: number;
		trial_index: number;
		kind: string;
		params_json: Record<string, number>;
		status: string;
		measured_s: number;
		pieces_delivered: number;
		incidents: number;
		double_drops: number;
		pieces_per_min: number | null;
		double_drop_rate: number | null;
		feasible: boolean | null;
		score: number | null;
	};
	type AutotuneStatus = {
		state: 'running' | 'idle';
		mode: 'session' | 'background' | null;
		machine_running: boolean;
		run: {
			id: string;
			status: string;
			best_trial_id: number | null;
		} | null;
		current_trial: {
			trial_index: number;
			kind: string;
			params: Record<string, number>;
			measured_s: number;
			duration_s: number;
			pieces_delivered: number;
			double_drops: number;
			waiting_for_machine: boolean;
		} | null;
		best_trial: {
			trial_index: number;
			params: Record<string, number>;
			score: number;
			pieces_per_min: number | null;
			double_drop_rate: number | null;
		} | null;
		trials: AutotuneTrial[];
		tunable_params: AutotuneParamMeta[];
		background: {
			enabled: boolean;
			enabled_at: number | null;
		};
	};

	let autotune = $state<AutotuneStatus | null>(null);
	let autotuneError = $state<string | null>(null);
	let autotuneBusy = $state(false);
	let trialDurationS = $state(120);
	let incidentWeight = $state(10);
	let maxDoubleDropPct = $state(5);
	let selectedParams = $state<Record<string, boolean>>({});
	let dataset = $state<AutotuneTrial[]>([]);

	// Settle is 3s (+1s config TTL) per trial, then trial length of RUNNING
	// time — pacing is in sorting time, not wall clock.
	const SETTLE_S = 4;
	let trialsPerHour = $derived(
		Number(trialDurationS) > 0 ? 3600 / (SETTLE_S + Number(trialDurationS)) : 0
	);
	let selectedParamCount = $derived(
		Object.values(selectedParams).filter(Boolean).length
	);
	// Very rough coverage guidance: ~30 trials per tuned parameter before the
	// search says anything trustworthy about this noisy an objective.
	let suggestedTrials = $derived(Math.max(30, selectedParamCount * 30));
	let suggestedHours = $derived(
		trialsPerHour > 0 ? suggestedTrials / trialsPerHour : 0
	);

	function paramLabel(key: string): string {
		return autotune?.tunable_params.find((p) => p.key === key)?.label ?? key;
	}

	async function loadAutotune() {
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception/autotune`
			);
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			const data: AutotuneStatus = await res.json();
			autotune = data;
			autotuneError = null;
			if (Object.keys(selectedParams).length === 0) {
				const next: Record<string, boolean> = {};
				for (const meta of data.tunable_params) next[meta.key] = true;
				selectedParams = next;
			}
		} catch (e: any) {
			autotuneError = e.message ?? 'Failed to load auto-tune status';
		}
	}

	async function loadDataset() {
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception/autotune/dataset`
			);
			if (!res.ok) return;
			const data = await res.json();
			dataset = data.trials ?? [];
		} catch {
			// chart is best-effort; status polling reports connectivity problems
		}
	}

	function settingsBody() {
		const param_keys = Object.entries(selectedParams)
			.filter(([, on]) => on)
			.map(([key]) => key);
		return {
			trial_duration_s: Number(trialDurationS),
			incident_weight: Number(incidentWeight),
			max_double_drop_rate: Number(maxDoubleDropPct) / 100,
			param_keys
		};
	}

	async function setBackground(enabled: boolean) {
		autotuneBusy = true;
		autotuneError = null;
		try {
			const body = enabled
				? { enabled: true, ...settingsBody() }
				: { enabled: false, apply: 'baseline' };
			const res = await fetch(
				`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception/autotune/background`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(body)
				}
			);
			if (!res.ok) {
				const resBody = await res.json().catch(() => ({}));
				throw new Error(resBody.detail ?? `HTTP ${res.status}`);
			}
			autotune = await res.json();
			if (!enabled) {
				setTimeout(() => {
					load();
					loadAutotune();
				}, 2000);
			}
		} catch (e: any) {
			autotuneError = e.message ?? 'Failed to toggle background exploration';
		} finally {
			autotuneBusy = false;
		}
	}

	async function startAutotune() {
		autotuneBusy = true;
		autotuneError = null;
		try {
			const body = settingsBody();
			if (body.param_keys.length === 0)
				throw new Error('Select at least one parameter to tune');
			const res = await fetch(
				`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception/autotune/start`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(body)
				}
			);
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			autotune = await res.json();
		} catch (e: any) {
			autotuneError = e.message ?? 'Failed to start auto-tune';
		} finally {
			autotuneBusy = false;
		}
	}

	async function stopAutotune(apply: 'baseline' | 'best' | 'keep') {
		autotuneBusy = true;
		autotuneError = null;
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception/autotune/stop`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ apply })
				}
			);
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			autotune = await res.json();
			// The tuner restores/applies config as it winds down — refresh the form
			// shortly after so it shows what is actually live.
			setTimeout(() => {
				load();
				loadAutotune();
			}, 2000);
		} catch (e: any) {
			autotuneError = e.message ?? 'Failed to stop auto-tune';
		} finally {
			autotuneBusy = false;
		}
	}

	function loadTrialIntoForm(params: Record<string, number>) {
		values = { ...values, ...params };
	}

	function fmt(value: number | null | undefined, digits = 1): string {
		if (value === null || value === undefined) return '—';
		return value.toFixed(digits);
	}

	function ddPct(trial: AutotuneTrial): number | null {
		if (trial.double_drop_rate !== null && trial.double_drop_rate !== undefined)
			return trial.double_drop_rate * 100;
		if (trial.pieces_delivered > 0) return (trial.double_drops / trial.pieces_delivered) * 100;
		return null;
	}

	// Scatter of the accumulated dataset: pieces/min vs double-drop rate, with
	// the current rate cap drawn as a vertical line. Reads the tradeoff frontier.
	const CHART = { w: 560, h: 240, l: 40, r: 10, t: 10, b: 30 };
	type ChartPoint = {
		x: number;
		y: number;
		px: number;
		py: number;
		feasible: boolean;
		label: string;
	};
	let chartPoints = $derived.by<ChartPoint[]>(() => {
		const pts: ChartPoint[] = [];
		for (const trial of dataset) {
			const pct = ddPct(trial);
			if (trial.pieces_per_min === null || pct === null) continue;
			pts.push({
				x: pct,
				y: trial.pieces_per_min,
				px: 0,
				py: 0,
				feasible: pct <= Number(maxDoubleDropPct),
				label: `${fmt(trial.pieces_per_min, 2)} pieces/min at ${fmt(pct, 1)}% double-drops (${trial.pieces_delivered} pieces)`
			});
		}
		const xMax = Math.max(10, Number(maxDoubleDropPct) * 2, ...pts.map((p) => p.x)) * 1.05;
		const yMax = Math.max(1, ...pts.map((p) => p.y)) * 1.1;
		const plotW = CHART.w - CHART.l - CHART.r;
		const plotH = CHART.h - CHART.t - CHART.b;
		for (const p of pts) {
			p.px = CHART.l + (p.x / xMax) * plotW;
			p.py = CHART.t + plotH - (p.y / yMax) * plotH;
		}
		return pts;
	});
	let chartXMax = $derived(
		Math.max(10, Number(maxDoubleDropPct) * 2, ...chartPoints.map((p) => p.x)) * 1.05
	);
	let chartYMax = $derived(Math.max(1, ...chartPoints.map((p) => p.y)) * 1.1);

	function chartX(pct: number): number {
		return CHART.l + (pct / chartXMax) * (CHART.w - CHART.l - CHART.r);
	}
	function chartY(ppm: number): number {
		return CHART.t + (CHART.h - CHART.t - CHART.b) * (1 - ppm / chartYMax);
	}
	function ticks(max: number, count: number): number[] {
		const step = max / count;
		return Array.from({ length: count + 1 }, (_, i) => i * step);
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			fields = data.fields;
			values = { ...data.config };
			guard.markSaved();
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
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception`, {
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
			guard.markSaved();
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
		loadAutotune();
		loadDataset();
	});

	$effect(() => {
		if (autotune?.state !== 'running') return;
		const interval = setInterval(loadAutotune, 2000);
		const datasetInterval = setInterval(loadDataset, 30000);
		return () => {
			clearInterval(interval);
			clearInterval(datasetInterval);
		};
	});
</script>

<svelte:head><title>Sorter - Feeder simple pulse tuning</title></svelte:head>

<PageHeader
	title="Feeder simple pulse"
	description="How the simple pulsing feeder moves pieces. Changes apply within about a second, with no restart."
/>

{#if !loading}
	<SettingsSaveBar {save} reset={load} {saving} dirty={guard.isDirty} />
{/if}

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}
{#if saved}
	<Alert tone="success">Saved. The changes apply within about a second.</Alert>
{/if}

{#if !loading}
	<Panel
		title="Exit pulse speed"
		description="Presets for how hard C2 and C3 push a piece off the exit edge into the next channel. One fills in the exit pulse fields below; review them, then Save."
		flush
	>
		<TuningPresets presets={exitPulsePresets} bind:values />
	</Panel>
{/if}

<Panel title="Parameters" description="Pulse distance and pause time for each region." flush>
	{#if loading}
		<div class="px-(--pad-panel) pb-(--pad-panel)">
			<div class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading</div>
		</div>
	{:else}
		<div class="divide-y divide-line">
			{#each sections as section}
				<div class="label px-(--pad-panel) py-1.5">{section.name}</div>
				{#each section.fields as field}
					<TuningParamRow {field} bind:values />
				{/each}
			{/each}
		</div>
	{/if}
	{#snippet footer()}
		<SettingsSaveBar {save} reset={load} {saving} dirty={guard.isDirty} disabled={loading} />
	{/snippet}
</Panel>

	<Panel
		title="Auto-tune"
		description="Searches for the fastest pulse parameters on this machine. Each trial applies a candidate and measures the pieces a minute into the classification channel. A trial counts only if its double-drop rate stays under the cap below; of those, the highest throughput wins. The trial clock runs only while sorting, so this runs alongside normal sorting."
	>
		{#if autotuneError}
			<Alert tone="danger">{autotuneError}</Alert>
		{/if}

		{#if autotune?.state === 'running'}
			<div class="flex flex-col gap-4">
				{#if autotune.mode === 'background'}
					<Alert tone="info">
						Background exploration is on: a new random candidate is tried every trial while you
						sort, and it keeps collecting across restarts until you turn it off.
					</Alert>
				{/if}
				{#if !autotune.machine_running}
					<Alert tone="warning">
						The machine isn't sorting, so the trial clock is paused. Start sorting to resume
						the measurement.
					</Alert>
				{/if}

				{#if autotune.current_trial}
					<div class="text-sm text-ink">
						<span class="font-medium">Trial {autotune.current_trial.trial_index}</span>
						<span class="text-ink-muted">({autotune.current_trial.kind})</span>:
						<span class="num">{fmt(autotune.current_trial.measured_s, 0)} s</span> of
						<span class="num">{fmt(autotune.current_trial.duration_s, 0)} s</span> measured,
						<span class="num">{autotune.current_trial.pieces_delivered}</span> pieces,
						<span class="num">{autotune.current_trial.double_drops}</span> double drops
					</div>
					<div class="text-sm text-ink-muted">
						{#each Object.entries(autotune.current_trial.params) as [key, value]}
							<div>{paramLabel(key)}: <span class="font-mono">{value}</span></div>
						{/each}
					</div>
				{:else}
					<div class="flex items-center gap-2 text-sm text-ink-muted">
						<Spinner size={14} /> Preparing the first trial
					</div>
				{/if}

				{#if autotune.mode === 'background'}
					<div class="flex flex-wrap gap-3">
						<Button
							variant="danger"
							onclick={() => setBackground(false)}
							loading={autotuneBusy}
						>
							Turn off background exploration
						</Button>
					</div>
				{:else}
					<div class="flex flex-wrap gap-3">
						<Button
							variant="danger"
							onclick={() => stopAutotune('baseline')}
							loading={autotuneBusy}
						>
							Stop and restore the baseline
						</Button>
						<Button
							variant="secondary"
							onclick={() => stopAutotune('best')}
							disabled={autotuneBusy || !autotune.best_trial}
						>
							Stop and apply the best
						</Button>
					</div>
				{/if}
			</div>
		{:else}
			<div class="flex flex-col gap-4">
				<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
					<Field label="Trial length" for="autotune-trial">
						<Input id="autotune-trial" type="number" bind:value={trialDurationS} unit="s sorting" />
					</Field>
					<Field label="Most double drops" for="autotune-dd">
						<Input id="autotune-dd" type="number" bind:value={maxDoubleDropPct} unit="%" />
					</Field>
					<Field
						label="Jam cost"
						for="autotune-jam"
						help="A jam or stall during a trial docks its score as if it delivered this many fewer pieces."
					>
						<Input id="autotune-jam" type="number" bind:value={incidentWeight} unit="pieces" />
					</Field>
				</div>

				<div class="text-sm text-ink-muted">
					Each trial costs about {SETTLE_S} s to settle plus {trialDurationS} s of sorting, so
					<span class="font-medium text-ink">{fmt(trialsPerHour, 1)} trials an hour of sorting</span>.
					With {selectedParamCount} parameters chosen, expect about {suggestedTrials} trials (about
					{fmt(suggestedHours, 0)} hours of sorting) before the search has covered the space. It runs
					until you stop it, and the data below builds up across runs, so stopping and resuming
					later loses nothing.
				</div>

				{#if autotune}
					<div class="flex flex-col gap-2">
						<div class="label">Parameters to tune</div>
						<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
							{#each autotune.tunable_params as meta}
								<Checkbox bind:checked={selectedParams[meta.key]}>
									{meta.label}
									<span class="num text-ink-muted">{meta.min} to {meta.max}</span>
								</Checkbox>
							{/each}
						</div>
					</div>
				{/if}

				<div class="flex flex-wrap gap-3">
					<Button variant="primary" onclick={startAutotune} loading={autotuneBusy}>
						Start tuning session
					</Button>
					<Button variant="secondary" onclick={() => setBackground(true)} loading={autotuneBusy}>
						Enable background exploration
					</Button>
				</div>
				<p class="text-sm text-ink-muted">
					A tuning session hunts for the best settings, spending three trials in four near the
					best so far. Background exploration instead tries purely random candidates during
					normal sorting: slower to find a winner, but it builds an even picture of the whole space
					and survives restarts until you turn it off.
				</p>
			</div>
		{/if}

		{#if autotune?.best_trial}
			<div class="mt-6 flex flex-col gap-2">
				<div class="label">Best so far</div>
				<div class="text-sm text-ink">
					Trial {autotune.best_trial.trial_index}:
					<span class="num font-medium">{fmt(autotune.best_trial.pieces_per_min, 2)} pieces a minute</span>
					at <span class="num">{fmt((autotune.best_trial.double_drop_rate ?? 0) * 100, 1)}%</span> double
					drops (score <span class="num">{fmt(autotune.best_trial.score, 2)}</span>)
				</div>
				<div class="text-sm text-ink-muted">
					{#each Object.entries(autotune.best_trial.params) as [key, value]}
						<div>{paramLabel(key)}: <span class="font-mono">{value}</span></div>
					{/each}
				</div>
				<div class="flex gap-3">
					<Button
						variant="secondary"
						size="sm"
						onclick={() => loadTrialIntoForm(autotune!.best_trial!.params)}
					>
						Load into form
					</Button>
				</div>
			</div>
		{/if}

		{#if chartPoints.length > 0}
			<div class="mt-6 flex flex-col gap-2">
				<div class="label">
					Throughput against double-drop rate, every trial collected ({chartPoints.length})
				</div>
				<div class="flex flex-wrap gap-4 text-sm text-ink">
					<span class="flex items-center gap-2">
						<svg width="10" height="10" class="text-success-ink"><rect width="10" height="10" fill="currentColor" /></svg>
						Within the cap
					</span>
					<span class="flex items-center gap-2">
						<svg width="10" height="10" class="text-danger-ink"><rect x="1" y="1" width="8" height="8" fill="none" stroke="currentColor" stroke-width="2" /></svg>
						Over the cap
					</span>
					<span class="flex items-center gap-2">
						<svg width="14" height="10" class="text-ink-muted"><line x1="7" y1="0" x2="7" y2="10" stroke="currentColor" stroke-width="2" stroke-dasharray="3 2" /></svg>
						{maxDoubleDropPct}% cap
					</span>
				</div>
				<div class="overflow-x-auto">
					<svg
						viewBox={`0 0 ${CHART.w} ${CHART.h}`}
						class="w-full max-w-3xl"
						role="img"
						aria-label="Scatter chart of pieces per minute versus double-drop rate for every collected trial"
					>
						{#each ticks(chartYMax, 4) as t}
							<line
								x1={CHART.l}
								x2={CHART.w - CHART.r}
								y1={chartY(t)}
								y2={chartY(t)}
								class="text-ink-muted"
								stroke="currentColor"
								stroke-opacity="0.15"
							/>
							<text
								x={CHART.l - 6}
								y={chartY(t) + 4}
								text-anchor="end"
								class="fill-current text-ink-muted"
								font-size="11"
							>
								{fmt(t, 0)}
							</text>
						{/each}
						{#each ticks(chartXMax, 5) as t}
							<text
								x={chartX(t)}
								y={CHART.h - CHART.b + 16}
								text-anchor="middle"
								class="fill-current text-ink-muted"
								font-size="11"
							>
								{fmt(t, 0)}%
							</text>
						{/each}
						<line
							x1={CHART.l}
							x2={CHART.w - CHART.r}
							y1={CHART.h - CHART.b}
							y2={CHART.h - CHART.b}
							class="text-ink-muted"
							stroke="currentColor"
							stroke-opacity="0.4"
						/>
						<line
							x1={chartX(Number(maxDoubleDropPct))}
							x2={chartX(Number(maxDoubleDropPct))}
							y1={CHART.t}
							y2={CHART.h - CHART.b}
							class="text-ink-muted"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-dasharray="4 3"
						/>
						{#each chartPoints as p}
							{#if p.feasible}
								<rect
									x={p.px - 3.5}
									y={p.py - 3.5}
									width="7"
									height="7"
									class="text-success-ink"
									fill="currentColor"
								>
									<title>{p.label}</title>
								</rect>
							{:else}
								<rect
									x={p.px - 3.5}
									y={p.py - 3.5}
									width="7"
									height="7"
									class="text-danger-ink"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
								>
									<title>{p.label}</title>
								</rect>
							{/if}
						{/each}
						<text
							x={(CHART.l + CHART.w - CHART.r) / 2}
							y={CHART.h - 2}
							text-anchor="middle"
							class="fill-current text-ink-muted"
							font-size="11"
						>
							Double-drop rate (% of pieces)
						</text>
						<text
							x={12}
							y={(CHART.t + CHART.h - CHART.b) / 2}
							text-anchor="middle"
							transform={`rotate(-90 12 ${(CHART.t + CHART.h - CHART.b) / 2})`}
							class="fill-current text-ink-muted"
							font-size="11"
						>
							Pieces a minute
						</text>
					</svg>
				</div>
			</div>
		{/if}

		{#if autotune && autotune.trials.length > 0}
			<div class="mt-6 flex flex-col gap-2">
				<div class="label">Trials in this run</div>
				<div class="-mx-(--pad-panel) overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th class="num">Trial</th>
								<th>Kind</th>
								<th class="num">Measured</th>
								<th class="num">Pieces</th>
								<th class="num">A minute</th>
								<th class="num">Incidents</th>
								<th class="num">Double drops</th>
								<th class="num">Score</th>
								<th><span class="sr-only">Load</span></th>
							</tr>
						</thead>
						<tbody>
							{#each autotune.trials as trial (trial.id)}
								<tr class:opacity-60={trial.feasible === false}>
									<td class="num">{trial.trial_index}</td>
									<td>{trial.kind}</td>
									<td class="num">{fmt(trial.measured_s, 0)} s</td>
									<td class="num">{trial.pieces_delivered}</td>
									<td class="num">{fmt(trial.pieces_per_min, 2)}</td>
									<td class="num">{trial.incidents}</td>
									<td class="num" class:text-danger-ink={trial.feasible === false}>
										{fmt(ddPct(trial), 1)}%
									</td>
									<td class="num font-medium">
										{trial.feasible === false ? 'Over the cap' : fmt(trial.score, 2)}
									</td>
									<td class="text-right">
										<Button
											variant="ghost"
											size="sm"
											onclick={() => loadTrialIntoForm(trial.params_json)}
										>
											Load
										</Button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
	</Panel>

<UnsavedChangesDialog {guard} />

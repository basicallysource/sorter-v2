<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Alert, Input } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import TuningParamRow from '$lib/components/settings/TuningParamRow.svelte';
	import TuningPresets from '$lib/components/settings/TuningPresets.svelte';
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

<svelte:head><title>Sorter - Feeder Pulse Perception Tuning</title></svelte:head>

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">Feeder — Simple Pulse Tuning</div>
		<div class="mt-1 text-sm text-text-muted">
			Changes take effect within ~1 second (no restart needed).
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if saved}
		<Alert variant="success">Saved. Changes apply within ~1 second.</Alert>
	{/if}

	{#if !loading}
		<SectionCard
			title="Exit pulse speed"
			description="One-click presets for how hard C2/C3 push a piece off the exit edge into the next channel. Clicking one fills in the exit-pulse fields below — review, then Save."
		>
			<TuningPresets presets={exitPulsePresets} bind:values />
		</SectionCard>
	{/if}

	<SectionCard
		title="Auto-tune"
		description="Searches for the fastest pulse parameters on this machine. Each trial applies a candidate config and measures pieces/min into the classification channel. A trial only counts as feasible if its double-drop rate stays under the cap below — among feasible trials, highest throughput wins. The trial clock only advances while sorting is running, so this runs on top of normal sorting."
	>
		{#if autotuneError}
			<Alert variant="danger">{autotuneError}</Alert>
		{/if}

		{#if autotune?.state === 'running'}
			<div class="flex flex-col gap-4">
				{#if autotune.mode === 'background'}
					<Alert variant="info">
						Background exploration is on — a new random candidate is applied every trial
						while you sort. It keeps collecting across restarts until you turn it off.
					</Alert>
				{/if}
				{#if !autotune.machine_running}
					<Alert variant="warning">
						Machine is not running — the trial clock is paused. Start sorting to resume
						measurement.
					</Alert>
				{/if}

				{#if autotune.current_trial}
					<div class="text-sm text-text">
						<span class="font-semibold">
							Trial {autotune.current_trial.trial_index}
						</span>
						<span class="text-text-muted">({autotune.current_trial.kind})</span>
						— {fmt(autotune.current_trial.measured_s, 0)}s /
						{fmt(autotune.current_trial.duration_s, 0)}s measured,
						{autotune.current_trial.pieces_delivered} pieces,
						{autotune.current_trial.double_drops} double-drops
					</div>
					<div class="text-sm text-text-muted">
						{#each Object.entries(autotune.current_trial.params) as [key, value]}
							<div>{paramLabel(key)}: <span class="font-mono">{value}</span></div>
						{/each}
					</div>
				{:else}
					<div class="text-sm text-text-muted">Preparing first trial…</div>
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
							Stop & restore baseline
						</Button>
						<Button
							variant="secondary"
							onclick={() => stopAutotune('best')}
							disabled={autotuneBusy || !autotune.best_trial}
						>
							Stop & apply best
						</Button>
					</div>
				{/if}
			</div>
		{:else}
			<div class="flex flex-col gap-4">
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
					<label class="flex flex-col gap-1 text-sm text-text">
						Trial length (s of sorting time)
						<Input type="number" bind:value={trialDurationS} />
					</label>
					<label class="flex flex-col gap-1 text-sm text-text">
						Max double-drop rate (%)
						<Input type="number" bind:value={maxDoubleDropPct} />
					</label>
					<label class="flex flex-col gap-1 text-sm text-text">
						Jam cost (pieces per incident)
						<Input type="number" bind:value={incidentWeight} />
						<span class="text-sm text-text-muted">
							If a jam/stall incident opens during a trial, its score is docked as if
							it had delivered this many fewer pieces.
						</span>
					</label>
				</div>

				<div class="text-sm text-text-muted">
					Each trial costs ~{SETTLE_S}s settle + {trialDurationS}s of sorting time ≈
					<span class="font-semibold text-text">{fmt(trialsPerHour, 1)} trials per hour of sorting</span>.
					With {selectedParamCount} parameters selected, expect to need roughly
					{suggestedTrials}+ trials (~{fmt(suggestedHours, 0)}+ hours of sorting) before
					the search has meaningfully covered the space. It runs until you stop it — the
					dataset below accumulates across runs, so stopping and resuming later loses
					nothing.
				</div>

				{#if autotune}
					<div class="flex flex-col gap-1">
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							Parameters to tune
						</div>
						<div class="grid grid-cols-1 gap-1 sm:grid-cols-2">
							{#each autotune.tunable_params as meta}
								<label class="flex items-center gap-2 text-sm text-text">
									<input type="checkbox" bind:checked={selectedParams[meta.key]} />
									{meta.label}
									<span class="text-text-muted">[{meta.min}–{meta.max}]</span>
								</label>
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
				<div class="text-sm text-text-muted">
					A tuning session hunts for the best config (75% refining around the best so
					far). Background exploration instead samples purely random candidates while you
					do normal sorting — slower to find a winner, but it builds an even dataset of
					the whole space and survives restarts until you turn it off.
				</div>
			</div>
		{/if}

		{#if autotune?.best_trial}
			<div class="mt-6 flex flex-col gap-2">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					Best so far
				</div>
				<div class="text-sm text-text">
					Trial {autotune.best_trial.trial_index} —
					<span class="font-semibold">{fmt(autotune.best_trial.pieces_per_min, 2)} pieces/min</span>
					at {fmt((autotune.best_trial.double_drop_rate ?? 0) * 100, 1)}% double-drops
					(score {fmt(autotune.best_trial.score, 2)})
				</div>
				<div class="text-sm text-text-muted">
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
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					Throughput vs double-drop rate — all collected trials ({chartPoints.length})
				</div>
				<div class="flex flex-wrap gap-4 text-sm text-text">
					<span class="flex items-center gap-2">
						<svg width="10" height="10" class="text-success"><rect width="10" height="10" fill="currentColor" /></svg>
						Within cap
					</span>
					<span class="flex items-center gap-2">
						<svg width="10" height="10" class="text-danger"><rect x="1" y="1" width="8" height="8" fill="none" stroke="currentColor" stroke-width="2" /></svg>
						Over cap
					</span>
					<span class="flex items-center gap-2">
						<svg width="14" height="10" class="text-text-muted"><line x1="7" y1="0" x2="7" y2="10" stroke="currentColor" stroke-width="2" stroke-dasharray="3 2" /></svg>
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
								class="text-text-muted"
								stroke="currentColor"
								stroke-opacity="0.15"
							/>
							<text
								x={CHART.l - 6}
								y={chartY(t) + 4}
								text-anchor="end"
								class="fill-current text-text-muted"
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
								class="fill-current text-text-muted"
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
							class="text-text-muted"
							stroke="currentColor"
							stroke-opacity="0.4"
						/>
						<line
							x1={chartX(Number(maxDoubleDropPct))}
							x2={chartX(Number(maxDoubleDropPct))}
							y1={CHART.t}
							y2={CHART.h - CHART.b}
							class="text-text-muted"
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
									class="text-success"
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
									class="text-danger"
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
							class="fill-current text-text-muted"
							font-size="11"
						>
							double-drop rate (% of pieces)
						</text>
						<text
							x={12}
							y={(CHART.t + CHART.h - CHART.b) / 2}
							text-anchor="middle"
							transform={`rotate(-90 12 ${(CHART.t + CHART.h - CHART.b) / 2})`}
							class="fill-current text-text-muted"
							font-size="11"
						>
							pieces/min
						</text>
					</svg>
				</div>
			</div>
		{/if}

		{#if autotune && autotune.trials.length > 0}
			<div class="mt-6 flex flex-col gap-2">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					Trials (this run)
				</div>
				<div class="overflow-x-auto">
					<table class="w-full text-sm text-text">
						<thead>
							<tr class="text-left text-text-muted">
								<th class="py-1 pr-3 font-normal">#</th>
								<th class="py-1 pr-3 font-normal">Kind</th>
								<th class="py-1 pr-3 font-normal">Measured</th>
								<th class="py-1 pr-3 font-normal">Pieces</th>
								<th class="py-1 pr-3 font-normal">P/min</th>
								<th class="py-1 pr-3 font-normal">Inc</th>
								<th class="py-1 pr-3 font-normal">DD%</th>
								<th class="py-1 pr-3 font-normal">Score</th>
								<th class="py-1 font-normal"></th>
							</tr>
						</thead>
						<tbody>
							{#each autotune.trials as trial (trial.id)}
								<tr class="border-t border-text-muted/20" class:opacity-60={trial.feasible === false}>
									<td class="py-1 pr-3">{trial.trial_index}</td>
									<td class="py-1 pr-3">{trial.kind}</td>
									<td class="py-1 pr-3">{fmt(trial.measured_s, 0)}s</td>
									<td class="py-1 pr-3">{trial.pieces_delivered}</td>
									<td class="py-1 pr-3">{fmt(trial.pieces_per_min, 2)}</td>
									<td class="py-1 pr-3">{trial.incidents}</td>
									<td class="py-1 pr-3" class:text-danger={trial.feasible === false}>
										{fmt(ddPct(trial), 1)}
									</td>
									<td class="py-1 pr-3 font-semibold">
										{trial.feasible === false ? 'over cap' : fmt(trial.score, 2)}
									</td>
									<td class="py-1">
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
	</SectionCard>

	<SectionCard
		title="Parameters"
		description="Pulse distance and pause time per region for the simple pulsing feeder."
	>
		{#if loading}
			<div class="text-sm text-text-muted">Loading…</div>
		{:else}
			<div class="flex flex-col gap-8">
				{#each sections as section}
					<div class="flex flex-col gap-2">
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

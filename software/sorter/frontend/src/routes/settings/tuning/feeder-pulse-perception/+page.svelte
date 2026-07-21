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
		score: number | null;
	};
	type AutotuneStatus = {
		state: 'running' | 'idle';
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
		} | null;
		trials: AutotuneTrial[];
		tunable_params: AutotuneParamMeta[];
	};

	let autotune = $state<AutotuneStatus | null>(null);
	let autotuneError = $state<string | null>(null);
	let autotuneBusy = $state(false);
	let trialDurationS = $state(120);
	let incidentWeight = $state(10);
	let doubleDropWeight = $state(3);
	let selectedParams = $state<Record<string, boolean>>({});

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

	async function startAutotune() {
		autotuneBusy = true;
		autotuneError = null;
		try {
			const param_keys = Object.entries(selectedParams)
				.filter(([, on]) => on)
				.map(([key]) => key);
			if (param_keys.length === 0) throw new Error('Select at least one parameter to tune');
			const res = await fetch(
				`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception/autotune/start`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						trial_duration_s: Number(trialDurationS),
						incident_weight: Number(incidentWeight),
						double_drop_weight: Number(doubleDropWeight),
						param_keys
					})
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
	});

	$effect(() => {
		if (autotune?.state !== 'running') return;
		const interval = setInterval(loadAutotune, 2000);
		return () => clearInterval(interval);
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
		description="Searches for the fastest pulse parameters on this machine. Each trial applies a candidate config, measures pieces/min into the classification channel while sorting is running, and penalizes incidents and double-drops. Start sorting from the dashboard first — trials only measure while the machine is running."
	>
		{#if autotuneError}
			<Alert variant="danger">{autotuneError}</Alert>
		{/if}

		{#if autotune?.state === 'running'}
			<div class="flex flex-col gap-4">
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
			</div>
		{:else}
			<div class="flex flex-col gap-4">
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
					<label class="flex flex-col gap-1 text-sm text-text">
						Trial length (s)
						<Input type="number" bind:value={trialDurationS} />
					</label>
					<label class="flex flex-col gap-1 text-sm text-text">
						Incident penalty (pieces)
						<Input type="number" bind:value={incidentWeight} />
					</label>
					<label class="flex flex-col gap-1 text-sm text-text">
						Double-drop penalty (pieces)
						<Input type="number" bind:value={doubleDropWeight} />
					</label>
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

				<div class="flex gap-3">
					<Button variant="primary" onclick={startAutotune} loading={autotuneBusy}>
						Start auto-tune
					</Button>
				</div>
			</div>
		{/if}

		{#if autotune?.best_trial}
			<div class="mt-6 flex flex-col gap-2">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					Best so far
				</div>
				<div class="text-sm text-text">
					Trial {autotune.best_trial.trial_index} — score
					<span class="font-semibold">{fmt(autotune.best_trial.score, 2)}</span>
					({fmt(autotune.best_trial.pieces_per_min, 2)} pieces/min)
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

		{#if autotune && autotune.trials.length > 0}
			<div class="mt-6 flex flex-col gap-2">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					Trials
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
								<th class="py-1 pr-3 font-normal">Dbl</th>
								<th class="py-1 pr-3 font-normal">Score</th>
								<th class="py-1 font-normal"></th>
							</tr>
						</thead>
						<tbody>
							{#each autotune.trials as trial (trial.id)}
								<tr class="border-t border-text-muted/20">
									<td class="py-1 pr-3">{trial.trial_index}</td>
									<td class="py-1 pr-3">{trial.kind}</td>
									<td class="py-1 pr-3">{fmt(trial.measured_s, 0)}s</td>
									<td class="py-1 pr-3">{trial.pieces_delivered}</td>
									<td class="py-1 pr-3">{fmt(trial.pieces_per_min, 2)}</td>
									<td class="py-1 pr-3">{trial.incidents}</td>
									<td class="py-1 pr-3">{trial.double_drops}</td>
									<td class="py-1 pr-3 font-semibold">{fmt(trial.score, 2)}</td>
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

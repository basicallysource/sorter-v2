<!--
	One recording of a motor drawn as a load curve: SG_RESULT over time with the
	trigger line, the speed gate and, if asked, TSTEP and CS_ACTUAL, with the
	facts of the recording and the numbers the threshold suggestion for its
	speed comes from. The tab opens it on the latest recording and shows a new
	one the moment it is made; a Select picks any other. Saving the suggestion
	is the tuning's step 4, not here.
-->
<script lang="ts">
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StallGuardChart from '$lib/components/StallGuardChart.svelte';
	import {
		fmtTime,
		type ChartPoint,
		type Run,
		type RunParams,
		type Suggestion
	} from '$lib/settings/stallguard';

	let {
		label,
		runs,
		run,
		points,
		loading,
		suggestion,
		onselect
	}: {
		// What the page calls the motor, in a sentence.
		label: string;
		runs: Run[];
		run: Run;
		points: ChartPoint[];
		loading: boolean;
		// The suggestion for this recording's speed, once it is read.
		suggestion: Suggestion | null;
		onselect: (run: Run) => void;
	} = $props();

	let showCs = $state(false);
	let showTstep = $state(true);

	const params = $derived<RunParams>(run.params ?? {});

	// The trigger line prefers the pair-based suggestion (the level that would be
	// saved) and falls back to the recording's own suggestion when there is no
	// stall to pair it with.
	const triggerLevel = $derived(
		suggestion?.trigger_level != null
			? suggestion.trigger_level
			: run.suggested_sgthrs != null
				? run.suggested_sgthrs * 2
				: null
	);
	// The gate is where the driver looks for a stall: the speed floor that would
	// be saved when it is measured from the recordings, else the one the sweep
	// filtered by.
	const gate = $derived(
		suggestion?.measured_cruise_tstep != null
			? suggestion.cruise_tstep
			: (params.cruise_tstep ?? null)
	);

	function kind(r: Run): string {
		return r.source === 'stall_test' ? 'Stall' : r.source === 'sweep' ? 'Free running' : r.source;
	}
	function speedOf(r: Run): string {
		const speed = r.params?.speed;
		return typeof speed === 'number' ? `${Math.abs(speed).toLocaleString()} µsteps/s` : '–';
	}
	// A label that only repeats the kind (the steps name their recordings so) is left out.
	const runOptions = $derived(
		runs.map((r) => ({
			value: r.id,
			label: `${fmtTime(r.started_at)} · ${kind(r)}${r.label && r.label !== kind(r) ? ` · ${r.label}` : ''} · ${speedOf(r)}`
		}))
	);
	function pick(id: string) {
		const next = runs.find((r) => r.id === id);
		if (next) onselect(next);
	}
</script>

<Panel
	title="Load curve"
	description="SG_RESULT over time. Lower means more load; a stall drops it toward 0."
>
	<div class="flex flex-col gap-4">
		<Field label="Recording" for="sg-recording">
			<Select
				id="sg-recording"
				value={run.id}
				options={runOptions}
				onchange={pick}
				class="max-w-xl"
			/>
		</Field>
		{@render facts([
			['Motor', run.stepper_name ?? '–'],
			['Speed', speedOf(run)],
			['Direction', params.direction ?? '–'],
			['Duration', `${params.duration_s ?? '–'} s`],
			...(run.sg_mean != null ? [['Mean SG', Math.round(run.sg_mean)] as [string, number]] : []),
			['IRUN', params.irun ?? '–'],
			['Acceleration', `${params.acceleration ?? '–'} µsteps/s²`],
			['Microsteps', params.microsteps ?? '–'],
			[
				'Chopper',
				params.stealthchop == null ? '–' : params.stealthchop ? 'StealthChop' : 'SpreadCycle'
			],
			['Loaded', params.loaded ? 'Yes' : 'No'],
			['Cruise TSTEP', params.cruise_tstep ?? '–']
		])}
		<div class="flex flex-wrap gap-x-5 gap-y-2">
			<Checkbox bind:checked={showCs}>CS_ACTUAL</Checkbox>
			<Checkbox bind:checked={showTstep}>TSTEP</Checkbox>
		</div>
		{#if loading}
			<p class="flex items-center gap-2 text-sm text-ink-muted">
				<Spinner size={14} /> Loading the samples
			</p>
		{:else}
			<div class="rounded-control bg-well p-3">
				<StallGuardChart
					{points}
					{triggerLevel}
					sgMean={run.sg_mean}
					cruiseTstep={gate}
					{showCs}
					{showTstep}
				/>
			</div>
		{/if}
		{#if suggestion}
			<section class="flex flex-col gap-3 rounded-control bg-well p-4">
				<h3 class="text-base font-semibold text-ink">Threshold suggestion for {label}</h3>
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
					SGTHRS is the geometric midpoint of the gap between the measured floor and dip. TCOOLTHRS
					is the measured cruise TSTEP (the fastest sustained) times 1.75, so the gate stays open
					through cruise and off while speeding up or slowing down.
					{#if !suggestion.enough_data}
						There is no stall at this speed to pair it with yet, so these numbers are provisional.
					{/if}
				</p>
			</section>
		{/if}
	</div>
</Panel>

{#snippet facts(items: [string, string | number][])}
	<dl class="flex flex-wrap gap-x-5 gap-y-1 text-sm">
		{#each items as [key, value] (key)}
			<div class="flex gap-1.5">
				<dt class="text-ink-muted">{key}</dt>
				<dd class="text-ink">{value}</dd>
			</div>
		{/each}
	</dl>
{/snippet}

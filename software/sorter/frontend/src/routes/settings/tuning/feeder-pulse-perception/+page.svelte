<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Alert } from '$lib/components/primitives';
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

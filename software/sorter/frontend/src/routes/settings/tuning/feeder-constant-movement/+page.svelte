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

	// Speed presets for the constant-movement feeder. Channels run continuously
	// at these speeds (output deg/s) and only stop on their gate conditions, so
	// the speeds directly set the throughput/separation trade-off. Each preset
	// sets the three channel speeds (merged over the current form, not
	// auto-saved).
	const speedPresets: TuningPreset[] = [
		{
			label: 'Cautious (1/4/7)',
			description:
				'Gentlest constant flow — C1 1°/s, C2 4°/s, C3 7°/s. Roughly matches simple-pulse effective throughput; lowest double-feed and tracking-loss risk. Start here.',
			values: {
				ch1_speed_output_deg_per_s: 1,
				ch2_speed_output_deg_per_s: 4,
				ch3_speed_output_deg_per_s: 7
			}
		},
		{
			label: 'Balanced (2/6/10)',
			description:
				'The defaults — C1 2°/s, C2 6°/s, C3 10°/s. Continuous flow with growing per-channel separation; moderate double-feed risk.',
			values: {
				ch1_speed_output_deg_per_s: 2,
				ch2_speed_output_deg_per_s: 6,
				ch3_speed_output_deg_per_s: 10
			}
		},
		{
			label: 'Fast (4/10/16)',
			description:
				'C1 4°/s, C2 10°/s, C3 16°/s. Noticeably faster hand-offs; watch the double-feed counter and for tracking loss on C2/C3.',
			values: {
				ch1_speed_output_deg_per_s: 4,
				ch2_speed_output_deg_per_s: 10,
				ch3_speed_output_deg_per_s: 16
			}
		},
		{
			label: 'Very fast (6/15/25)',
			description:
				'C1 6°/s, C2 15°/s, C3 25°/s. Stress test — expect tracking strain and clump arrivals; only for probing the ceiling.',
			values: {
				ch1_speed_output_deg_per_s: 6,
				ch2_speed_output_deg_per_s: 15,
				ch3_speed_output_deg_per_s: 25
			}
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
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-constant-movement`);
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
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-constant-movement`, {
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

<svelte:head><title>Sorter - Feeder Constant Movement Tuning</title></svelte:head>

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">Feeder — Constant Movement Tuning</div>
		<div class="mt-1 text-sm text-text-muted">
			Channels run continuously at their configured speeds and only stop when the next channel
			can't accept a piece. Changes take effect within ~1 second (no restart needed). Requires
			Feeder Mode = Constant Movement in General settings.
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
			title="Speed presets"
			description="One-click presets for the three channel speeds (C1/C2/C3 in output deg/s). Clicking one fills in the speed fields below — review, then Save."
		>
			<TuningPresets presets={speedPresets} bind:values />
		</SectionCard>
	{/if}

	<SectionCard
		title="Parameters"
		description="Per-channel constant speeds and the stop/start gate behavior."
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

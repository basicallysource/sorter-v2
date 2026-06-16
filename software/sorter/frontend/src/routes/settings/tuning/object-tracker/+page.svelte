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

	type TrackerInfo = {
		type: string;
		label: string;
		description: string;
		fields: TuningFieldMeta[];
		config: TuningValues;
	};

	// Presets per tracker type. They mainly bias toward keeping ids through the
	// curve and brief disappearances — the failure mode on a circular feed.
	const presetsByType: Record<string, TuningPreset[]> = {
		bytetrack: [
			{
				label: 'Balanced',
				description: 'ByteTrack baseline — ~1 s occlusion hold, standard matching.',
				values: {
					track_activation_threshold: 0.1,
					minimum_consecutive_frames: 1,
					minimum_matching_threshold: 0.9,
					lost_track_buffer: 30,
					frame_rate: 30
				}
			},
			{
				label: 'Sensitive',
				description:
					'~2 s hold and looser matching. Note: ByteTrack still loses ids when a piece curves or leaves the frame — use the Angular tracker for that.',
				values: {
					track_activation_threshold: 0.1,
					minimum_consecutive_frames: 1,
					minimum_matching_threshold: 0.95,
					lost_track_buffer: 60,
					frame_rate: 30
				}
			}
		],
		angular: [
			{
				label: 'Balanced',
				description: 'Default gate and ~2.5 s coast. Good starting point for 0–2 pieces.',
				values: {
					min_hits: 1,
					activation_score: 0.1,
					angular_gate_deg: 14,
					radius_gate_frac: 0.3,
					use_color: true,
					color_gate: 0.22,
					velocity_smoothing: 0.5,
					max_coast_s: 2.5
				}
			},
			{
				label: 'Sticky (recommended)',
				description:
					'Wide angular gate + 4 s coast so a fast piece that rounds the curve or leaves the frame keeps its id. Color gate on to avoid mixing up pieces.',
				values: {
					min_hits: 1,
					activation_score: 0.05,
					angular_gate_deg: 24,
					radius_gate_frac: 0.35,
					use_color: true,
					color_gate: 0.28,
					velocity_smoothing: 0.5,
					max_coast_s: 4.0
				}
			},
			{
				label: 'Tight',
				description:
					'Narrow gate, strict color, short coast — for when 3–4 pieces crowd close together and you want to avoid id swaps.',
				values: {
					min_hits: 1,
					activation_score: 0.1,
					angular_gate_deg: 8,
					radius_gate_frac: 0.2,
					use_color: true,
					color_gate: 0.15,
					velocity_smoothing: 0.6,
					max_coast_s: 1.5
				}
			}
		]
	};

	let activeType = $state('');
	let selectedType = $state('');
	let trackers = $state<TrackerInfo[]>([]);
	let valuesByType = $state<Record<string, TuningValues>>({});
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);

	let current = $derived(trackers.find((t) => t.type === selectedType));
	let sections = $derived(current ? groupTuningSections(current.fields) : []);
	let presets = $derived(presetsByType[selectedType] ?? []);

	function applyData(data: any) {
		activeType = data.active_type;
		trackers = data.trackers ?? [];
		const next: Record<string, TuningValues> = {};
		for (const t of trackers) next[t.type] = { ...t.config };
		valuesByType = next;
		if (!selectedType || !trackers.some((t) => t.type === selectedType)) {
			selectedType = activeType || trackers[0]?.type || '';
		}
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/object-tracker`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			applyData(await res.json());
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
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/object-tracker`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					active_type: selectedType,
					type: selectedType,
					config: valuesByType[selectedType]
				})
			});
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			applyData(await res.json());
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

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">Object Tracker</div>
		<div class="mt-1 text-sm text-text-muted">
			Cross-frame identity for classification-channel detections — assigns each piece a stable id
			that survives brief detector dropouts. Pick which tracker to run; its parameters are shown
			below. Changes take effect within ~1 second (no restart needed).
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if saved}
		<Alert variant="success">Saved. Changes apply within ~1 second.</Alert>
	{/if}

	{#if loading}
		<div class="text-sm text-text-muted">Loading…</div>
	{:else}
		<SectionCard
			title="Tracker"
			description="Which tracker runs on the channel. Saving switches to the selected tracker and stores its parameters."
		>
			<div class="flex flex-wrap gap-2">
				{#each trackers as t}
					<Button
						variant={selectedType === t.type ? 'primary' : 'secondary'}
						size="sm"
						onclick={() => (selectedType = t.type)}
					>
						{t.label}{t.type === activeType ? ' (current)' : ''}
					</Button>
				{/each}
			</div>
			{#if current}
				<div class="mt-3 text-sm text-text-muted">{current.description}</div>
			{/if}
		</SectionCard>

		{#if presets.length}
			<SectionCard
				title="Presets"
				description="One-click starting points for the selected tracker. Click one to fill the form below, then Save."
			>
				<TuningPresets {presets} bind:values={valuesByType[selectedType]} />
			</SectionCard>
		{/if}

		<SectionCard title="Parameters" description="Parameters for the selected tracker.">
			<div class="flex flex-col gap-8">
				{#each sections as section}
					<div class="flex flex-col gap-4">
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							{section.name}
						</div>
						{#each section.fields as field}
							<TuningParamRow {field} bind:values={valuesByType[selectedType]} />
						{/each}
					</div>
				{/each}
			</div>

			<div class="mt-6 flex gap-3">
				<Button variant="primary" onclick={save} loading={saving}>Save</Button>
				<Button variant="secondary" onclick={load} disabled={saving}>Reset to saved</Button>
			</div>
		</SectionCard>
	{/if}
</div>

<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import TuningParamRow from '$lib/components/settings/TuningParamRow.svelte';
	import TuningPresets from '$lib/components/settings/TuningPresets.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import SettingsSaveBar from '$lib/components/settings/SettingsSaveBar.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import RadioGroup from '$lib/components/ui/RadioGroup.svelte';
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

<svelte:head><title>Sorter - Object tracker tuning</title></svelte:head>

<PageHeader
	title="Object tracker"
	description="Identity across frames for the classification channel's detections: each piece keeps one id through brief detector dropouts. Choose which tracker runs; its parameters are below. Changes apply within about a second, with no restart."
/>

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}
{#if saved}
	<Alert tone="success">Saved. The changes apply within about a second.</Alert>
{/if}

{#if loading}
	<div class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading</div>
{:else}
	<Panel
		title="Tracker"
		description="Which tracker runs on the channel. Saving switches to the chosen one and stores its parameters."
	>
		<RadioGroup
			name="tracker"
			label="Tracker"
			bind:value={selectedType}
			options={trackers.map((t) => ({
				value: t.type,
				label: t.type === activeType ? `${t.label} (running)` : t.label,
				help: t.description
			}))}
		/>
	</Panel>

	{#if presets.length}
		<Panel
			title="Presets"
			description="Starting points for the chosen tracker. One fills in the parameters below; then Save."
			flush
		>
			<TuningPresets {presets} bind:values={valuesByType[selectedType]} />
		</Panel>
	{/if}

	<Panel title="Parameters" description="The chosen tracker's parameters." flush>
		<div class="divide-y divide-line">
			{#each sections as section}
				<div class="label px-(--pad-panel) py-1.5">{section.name}</div>
				{#each section.fields as field}
					<TuningParamRow {field} bind:values={valuesByType[selectedType]} />
				{/each}
			{/each}
		</div>
		{#snippet footer()}
			<SettingsSaveBar {save} reset={load} {saving} />
		{/snippet}
	</Panel>
{/if}

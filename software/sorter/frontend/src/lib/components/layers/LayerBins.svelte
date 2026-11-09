<!--
	How many layers of bins the machine has and how many bins each holds,
	counted from the top. Every other setting of a layer (its bin limits, its
	servo angles) is sent back as it was loaded, so this changes only the
	counts.

	`base` is the machine's address. `fixedBottom` says the bottom layer's door
	is fixed shut. `onsaved` runs after a save, for a page that shows what
	depends on the layers.
-->
<script lang="ts">
	import Minus from '@lucide/svelte/icons/minus';
	import Plus from '@lucide/svelte/icons/plus';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { requestBackendRestart } from '$lib/backend';
	import { errorMessage } from '$lib/api/http';
	import {
		getStorageLayers,
		saveStorageLayers,
		updateFrom,
		type StorageLayerUpdate,
		type StorageLayers
	} from '$lib/api/storage-layers';

	let {
		base,
		fixedBottom,
		onsaved
	}: {
		base: string;
		fixedBottom: boolean;
		onsaved?: () => void | Promise<void>;
	} = $props();

	const MAX_LAYERS = 8;

	let loaded = $state<StorageLayers | null>(null);
	let loadError = $state<string | null>(null);
	let draft = $state<StorageLayerUpdate[]>([]);
	let saving = $state(false);
	let saveError = $state<string | null>(null);
	let saved = $state(false);
	let restartNeeded = $state(false);
	let restarting = $state(false);
	let restartMessage = $state<string | null>(null);

	const counts = $derived((loaded?.allowed_bin_counts ?? [6, 12, 18, 24, 30]).map((count) => ({ value: String(count), label: String(count) })));
	const changed = $derived(
		!!loaded &&
			(draft.length !== loaded.layers.length ||
				draft.some((layer, index) => layer.bin_count !== loaded!.layers[index].bin_count))
	);
	const totalBins = $derived(draft.reduce((sum, layer) => sum + layer.bin_count, 0));

	async function load() {
		loadError = null;
		try {
			loaded = await getStorageLayers(base);
			draft = loaded.layers.map(updateFrom);
		} catch (e) {
			loadError = errorMessage(e, 'The layers did not load.');
		}
	}

	function setCount(index: number, count: string) {
		draft = draft.map((layer, i) => (i === index ? { ...layer, bin_count: Number(count) } : layer));
		saved = false;
	}

	function addLayer() {
		const last = draft[draft.length - 1];
		draft = [
			...draft,
			{
				bin_count: last?.bin_count ?? 12,
				enabled: true,
				servo_open_angle: null,
				servo_closed_angle: null,
				max_pieces_per_bin: null,
				max_dimension_mm: null
			}
		];
		saved = false;
	}

	function removeLayer() {
		draft = draft.slice(0, -1);
		saved = false;
	}

	async function save() {
		saving = true;
		saveError = null;
		try {
			const result = await saveStorageLayers(base, draft);
			loaded = result.settings;
			draft = result.settings.layers.map(updateFrom);
			restartNeeded = restartNeeded || result.restart_required;
			saved = true;
			await onsaved?.();
		} catch (e) {
			saveError = errorMessage(e, 'The layers were not saved.');
		} finally {
			saving = false;
		}
	}

	async function restart() {
		restarting = true;
		restartMessage = null;
		const ok = await requestBackendRestart(base);
		restarting = false;
		if (ok) {
			restartNeeded = false;
			restartMessage = 'The software is starting again. This page catches up when it is back.';
		} else {
			restartMessage = 'The software did not start again. Restart the machine to use the new layers.';
		}
	}

	$effect(() => {
		void load();
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if loadError}
		<Alert tone="danger" title="The layers did not load">
			{loadError}
			{#snippet actions()}
				<Button size="sm" icon={RotateCcw} onclick={() => void load()}>Try again</Button>
			{/snippet}
		</Alert>
	{:else if !loaded}
		<Panel>
			<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={16} /> Loading the layers</p>
		</Panel>
	{:else}
		<Panel
			title="Layers"
			description="Counted from the top: layer 1 is the top one. {draft.length} {draft.length === 1
				? 'layer'
				: 'layers'}, {totalBins} bins."
			flush
		>
			<div class="divide-y divide-line">
				{#each draft as layer, index (index)}
					{@const bottom = index === draft.length - 1}
					<SettingRow
						label="Layer {index + 1}"
						help={bottom && fixedBottom
							? 'The bottom layer. Its door is fixed shut: it has no servo, and catches what every door above lets past.'
							: index === 0
								? 'The top layer.'
								: bottom
									? 'The bottom layer.'
									: undefined}
					>
						{#snippet tags()}
							{#if bottom && fixedBottom}<Badge>Fixed door</Badge>{/if}
						{/snippet}
						<SegmentedControl
							label="Bins on layer {index + 1}"
							size="sm"
							value={String(layer.bin_count)}
							options={counts}
							onchange={(count) => setCount(index, count)}
						/>
					</SettingRow>
				{/each}
				<div class="flex flex-wrap gap-2 px-(--pad-panel) py-(--pad-row)">
					<Button icon={Plus} disabled={draft.length >= MAX_LAYERS || saving} onclick={addLayer}>
						Add a layer
					</Button>
					<Button
						variant="ghost"
						icon={Minus}
						disabled={draft.length <= 1 || saving}
						onclick={removeLayer}
					>
						Remove the bottom layer
					</Button>
				</div>
			</div>
			{#snippet footer()}
				<Button variant="primary" loading={saving} disabled={!changed} onclick={() => void save()}>
					Save the layers
				</Button>
			{/snippet}
		</Panel>

		{#if saveError}
			<Alert tone="danger">{saveError}</Alert>
		{:else if saved && !changed && !restartNeeded}
			<p class="text-sm text-success-ink">The layers are saved.</p>
		{/if}
		{#if restartNeeded}
			<Alert tone="warning" title="Start the software again to use the new layers">
				The machine keeps sorting into the layers it started with until then.
				{#snippet actions()}
					<Button size="sm" icon={RotateCcw} loading={restarting} onclick={() => void restart()}>
						Start it again
					</Button>
				{/snippet}
			</Alert>
		{/if}
		{#if restartMessage}<p class="text-sm text-ink-muted">{restartMessage}</p>{/if}
	{/if}
</div>

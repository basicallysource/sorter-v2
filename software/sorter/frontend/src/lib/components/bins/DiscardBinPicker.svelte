<!--
	Choose the discard bin: the layer, the section round the chute, and the
	bin in it. With none chosen yet it suggests one on the bottom layer, the
	first that takes no category. Saving sends it to the machine at once; the
	parent shows it with the layout it reloads.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import { saveDiscardBin, sameBin, type BinAddress } from '$lib/api/chute';
	import { errorMessage } from '$lib/api/http';
	import type { LayerInfo } from './types';

	let {
		base,
		layers,
		current,
		onsaved
	}: {
		base: string;
		layers: LayerInfo[];
		// The discard bin as saved, or null.
		current: BinAddress | null;
		onsaved: (bin: BinAddress | null) => void | Promise<void>;
	} = $props();

	function suggestion(): BinAddress | null {
		const bottom = layers[layers.length - 1];
		if (!bottom || bottom.bins.length === 0) return null;
		const bin = bottom.bins.find((entry) => entry.category_ids.length === 0) ?? bottom.bins[0];
		return { layer_index: bottom.layer_index, section_index: bin.section_index, bin_index: bin.bin_index };
	}

	let layer = $state('');
	let section = $state('');
	let bin = $state('');
	let saving = $state(false);
	let clearing = $state(false);
	let error = $state<string | null>(null);

	// Follow what is saved (or the suggestion) when that changes, and only
	// then: a layout that reloads while someone picks leaves the pick alone.
	const startKey = $derived(
		current
			? `${current.layer_index}:${current.section_index}:${current.bin_index}`
			: `none:${layers.length}`
	);
	$effect(() => {
		void startKey;
		untrack(() => {
			const start = current ?? suggestion();
			layer = start ? String(start.layer_index) : '';
			section = start ? String(start.section_index) : '';
			bin = start ? String(start.bin_index) : '';
		});
	});

	const chosenLayer = $derived(layers.find((entry) => String(entry.layer_index) === layer) ?? null);
	const layerOptions = $derived(
		layers.map((entry, index) => ({
			value: String(entry.layer_index),
			label: `Layer ${entry.layer_index + 1}${index === 0 ? ' (top)' : index === layers.length - 1 ? ' (bottom)' : ''}`
		}))
	);
	const sectionOptions = $derived(
		Array.from({ length: chosenLayer?.section_count ?? 0 }, (_, index) => ({
			value: String(index),
			label: `Section ${index + 1}`
		}))
	);
	const binOptions = $derived(
		(chosenLayer?.bins ?? [])
			.filter((entry) => String(entry.section_index) === section)
			.sort((a, b) => a.bin_index - b.bin_index)
			.map((entry) => ({
				value: String(entry.bin_index),
				label: `Bin ${entry.global_index + 1}`,
				hint: entry.category_ids.length ? 'Takes a category now' : undefined
			}))
	);
	const picked = $derived<BinAddress | null>(
		layer !== '' && section !== '' && bin !== ''
			? { layer_index: Number(layer), section_index: Number(section), bin_index: Number(bin) }
			: null
	);
	const unchanged = $derived(sameBin(picked, current));

	function pickLayer(value: string) {
		layer = value;
		section = '0';
		bin = '0';
	}

	function pickSection(value: string) {
		section = value;
		bin = '0';
	}

	async function save(address: BinAddress | null) {
		if (address) saving = true;
		else clearing = true;
		error = null;
		try {
			await saveDiscardBin(base, address);
			await onsaved(address);
		} catch (e) {
			error = errorMessage(e, 'The discard bin was not saved.');
		} finally {
			saving = false;
			clearing = false;
		}
	}
</script>

<div class="flex flex-col gap-4">
	<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
		<Field label="Layer" for="discard-layer">
			<Select id="discard-layer" value={layer} options={layerOptions} onchange={pickLayer} />
		</Field>
		<Field label="Section" for="discard-section">
			<Select id="discard-section" value={section} options={sectionOptions} onchange={pickSection} />
		</Field>
		<Field label="Bin" for="discard-bin">
			<Select id="discard-bin" bind:value={bin} options={binOptions} />
		</Field>
	</div>
	{#if error}<Alert tone="danger">{error}</Alert>{/if}
	<div class="flex flex-wrap items-center justify-end gap-2">
		{#if !current}
			<span class="mr-auto text-sm text-ink-muted">Suggested: a bin on the bottom layer.</span>
		{/if}
		{#if current}
			<Button variant="ghost" loading={clearing} disabled={saving} onclick={() => void save(null)}>
				Have no discard bin
			</Button>
		{/if}
		<Button
			variant="primary"
			icon={Check}
			loading={saving}
			disabled={!picked || unchanged || clearing}
			onclick={() => void save(picked)}
		>
			{current ? 'Use this bin instead' : 'Use this bin'}
		</Button>
	</div>
</div>

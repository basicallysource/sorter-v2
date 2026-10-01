<!--
	A condition's value when it names LEGO parts: the chosen parts are PartTile
	rows (picture, name, the BrickLink ID), each with a button to take it out,
	and under them a search box to find the next one by name or number. The
	value stored is the part's BrickLink ID for a BrickLink ID condition and its
	Rebrickable number for a Rebrickable one; nobody types either.
-->
<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import type { ProfileCatalogSearchResult } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { catalog, infoFromSearch, type PartRef } from '../catalog.svelte';
	import { toList } from '../fields';
	import PartPicker from '../PartPicker.svelte';
	import ValueBox from './ValueBox.svelte';

	let {
		ref,
		multi,
		value,
		invalid = false,
		onchange
	}: {
		ref: PartRef;
		multi: boolean;
		value: unknown;
		invalid?: boolean;
		onchange: (value: unknown) => void;
	} = $props();

	// More parts than this are folded under "Show all".
	const SHOWN = 6;

	const ids = $derived(toList(value).map((v) => String(v)));
	let showAll = $state(false);
	const visible = $derived(showAll ? ids : ids.slice(0, SHOWN));
	const picking = $derived(multi || ids.length === 0);

	// A saved value the editor has not met yet is looked up for its picture.
	$effect(() => {
		for (const id of visible) if (catalog.part(ref, id) === undefined) void catalog.ensurePart(ref, id);
	});

	function add(part: ProfileCatalogSearchResult) {
		const info = infoFromSearch(part);
		const id = ref === 'bl_part' ? info.bricklinkId : part.part_num;
		if (!id) return;
		if (catalog.part(ref, id) === undefined) catalog.remember(ref, id, info);
		if (multi) onchange(ids.includes(id) ? ids : [...ids, id]);
		else onchange(id);
	}

	function remove(id: string) {
		onchange(multi ? ids.filter((v) => v !== id) : '');
	}
</script>

<ValueBox {invalid} class="overflow-hidden">
	{#if visible.length > 0}
		<ul class="divide-y divide-line">
			{#each visible as id (id)}
				{@const info = catalog.part(ref, id)}
				<li class="relative py-1 pr-12 pl-2">
					{#if info}
						<PartTile
							padded={false}
							name={info.name}
							imgUrl={info.imgUrl}
							bricklinkId={info.bricklinkId}
							partNum={info.partNum}
						/>
					{:else if info === null}
						<div class="flex min-h-12 items-center gap-3 text-sm">
							<span class="font-mono text-ink">{id}</span>
							<span class="text-ink-muted">Not in the catalog</span>
						</div>
					{:else}
						<div class="flex min-h-12 items-center gap-2 text-sm text-ink-muted">
							<Spinner size={14} />Looking up {id}
						</div>
					{/if}
					<div class="absolute top-1/2 right-1.5 -translate-y-1/2">
						<Button
							variant="ghost"
							size="sm"
							icon={X}
							label="Remove {info?.name ?? id}"
							onclick={() => remove(id)}
						/>
					</div>
				</li>
			{/each}
		</ul>
		{#if ids.length > SHOWN}
			<div class="border-t border-line px-2 py-1">
				<Button variant="ghost" size="sm" onclick={() => (showAll = !showAll)}>
					{showAll ? 'Show fewer' : `Show all ${ids.length.toLocaleString('en-US')} parts`}
				</Button>
			</div>
		{/if}
	{/if}
	{#if picking}
		<div class={visible.length > 0 ? 'border-t border-line' : ''}>
			<PartPicker
				label="Search parts to add"
				placeholder={ids.length > 0 ? 'Search for another part' : 'Search parts by name or number'}
				needsBricklinkId={ref === 'bl_part'}
				onpick={add}
			/>
		</div>
	{/if}
</ValueBox>

<!--
	Which kit a kit rule collects: one of the person's kits, a new kit made from
	a LEGO set's parts, or a new empty kit made by hand (its parts are added on
	the kit's own page, which opens in another tab so the draft here stays as it
	is). It lives in a dialog; choosing one hands the kit back and the dialog
	closes.
-->
<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import { api, type Kit, type KitSummary } from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import PartImage from '$lib/components/PartImage.svelte';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import { plural } from './rules';

	type Source = 'mine' | 'set' | 'hand';
	type ChosenSet = { set_num: string; name: string; year: number; num_parts: number; img_url: string | null };

	let {
		onpick
	}: {
		// The kit chosen or made; `open` when its page should be opened to fill it in.
		onpick: (kit: Kit | KitSummary, open: boolean) => void;
	} = $props();

	const uid = $props.id();

	let source = $state<Source>('mine');
	let kits = $state.raw<KitSummary[] | null>(null);
	let query = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);
	let chosenSet = $state<ChosenSet | null>(null);
	let includeSpares = $state(false);
	let handName = $state('');

	$effect(() => {
		api
			.listKits({ scope: 'mine' })
			.then((list) => (kits = list))
			.catch((e: { error?: string }) => {
				kits = [];
				error = e?.error ?? 'Your kits could not be loaded.';
			});
	});

	const shown = $derived.by(() => {
		const needle = query.trim().toLowerCase();
		const list = kits ?? [];
		return needle
			? list.filter((kit) => kit.name.toLowerCase().includes(needle) || (kit.set_num ?? '').toLowerCase().includes(needle))
			: list;
	});

	async function make(work: () => Promise<Kit>, open: boolean) {
		busy = true;
		error = null;
		try {
			onpick(await work(), open);
		} catch (e) {
			error = (e as { error?: string })?.error ?? 'The kit could not be made.';
		}
		busy = false;
	}

	function facts(kit: KitSummary): string {
		const parts = `${plural(kit.line_count, 'line')}, ${plural(kit.total_quantity, 'piece')}`;
		return kit.source === 'set' && kit.set_num ? `${parts} · LEGO set ${kit.set_num}` : parts;
	}
</script>

<div class="flex flex-col gap-4">
	<Tabs
		label="Where the kit comes from"
		bind:value={source}
		items={[
			{ value: 'mine', label: 'Your kits', count: kits?.length },
			{ value: 'set', label: 'From a LEGO set' },
			{ value: 'hand', label: 'Make one by hand' }
		]}
	/>

	{#if error}<Alert tone="danger">{error}</Alert>{/if}

	{#if source === 'mine'}
		{#if kits === null}
			<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} />Loading your kits</p>
		{:else if kits.length === 0}
			<p class="rounded-control bg-well px-3 py-6 text-center text-sm text-ink-muted">
				You have no kits yet. Make one from a LEGO set, or by hand.
			</p>
		{:else}
			<Input
				type="search"
				size="sm"
				placeholder="Search your kits"
				aria-label="Search your kits"
				autocomplete="off"
				bind:value={query}
			/>
			<ul class="flex max-h-96 flex-col gap-0.5 overflow-y-auto">
				{#each shown as kit (kit.id)}
					<li>
						<button
							type="button"
							onclick={() => onpick(kit, false)}
							class="flex w-full items-center gap-3 rounded-control px-2 py-2 text-left transition-colors hover:bg-hover active:bg-pressed"
						>
							<PartImage src={kit.image_url} class="size-12 shrink-0" />
							<span class="min-w-0 flex-1">
								<span class="block truncate text-sm font-medium text-ink">{kit.name}</span>
								<span class="block truncate text-sm text-ink-muted">{facts(kit)}</span>
							</span>
						</button>
					</li>
				{:else}
					<li class="px-2 py-3 text-sm text-ink-muted">No kit matches "{query.trim()}".</li>
				{/each}
			</ul>
		{/if}
	{:else if source === 'set'}
		{#if chosenSet}
			<div class="flex flex-col gap-3 rounded-control bg-well p-3">
				<div class="flex items-center gap-3">
					<PartImage src={chosenSet.img_url} class="size-16 shrink-0" />
					<div class="min-w-0">
						<div class="truncate text-sm font-medium text-ink">{chosenSet.name}</div>
						<div class="text-sm text-ink-muted">
							<span class="num">{chosenSet.set_num}</span> · {chosenSet.year} · {plural(chosenSet.num_parts, 'part')}
						</div>
					</div>
				</div>
				<Checkbox bind:checked={includeSpares}>Include the spare parts</Checkbox>
				<div class="flex flex-wrap justify-end gap-2">
					<Button variant="ghost" onclick={() => (chosenSet = null)}>Choose another set</Button>
					<Button
						variant="primary"
						loading={busy}
						onclick={() =>
							chosenSet &&
							make(() => api.createKitFromSet({ set_num: chosenSet!.set_num, include_spares: includeSpares }), false)}
					>
						Make the kit
					</Button>
				</div>
			</div>
		{:else}
			<SetSearch onSelect={(set) => (chosenSet = set)} />
		{/if}
	{:else}
		<div class="flex flex-col gap-3">
			<p class="text-sm text-ink-muted">
				Make an empty kit and fill it in on its own page, which opens in another tab. This page keeps your changes.
			</p>
			<Field label="Name of the kit" for="{uid}-hand-name">
				<Input id="{uid}-hand-name" placeholder="For example: Mixed red bricks" autocomplete="off" bind:value={handName} />
			</Field>
			<div class="flex justify-end">
				<Button
					variant="primary"
					icon={Plus}
					loading={busy}
					disabled={!handName.trim()}
					onclick={() => make(() => api.createKit({ name: handName.trim(), parts: [] }), true)}
				>
					Make the kit and open it
				</Button>
			</div>
		</div>
	{/if}
</div>

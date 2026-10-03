<!--
	Find a LEGO part by name or number and pick it from its picture: type, and the
	catalog's parts appear under the field as PartTile rows, the same in every
	place a part is shown. The field has no outline of its own, so put it inside
	a box (a condition's value, the "where would a piece go" box) that draws one.
	Enter picks the first part found, or with `onenter` hands over what was typed.
-->
<script lang="ts">
	import { api, type ProfileCatalogSearchResult } from '$lib/api';
	import PartTile from '$lib/components/PartTile.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { bricklinkIdsOf } from './catalog.svelte';

	let {
		label = 'Search the parts',
		placeholder = 'Search by name or number',
		needsBricklinkId = false,
		onpick,
		onenter
	}: {
		label?: string;
		placeholder?: string;
		// A part without a BrickLink ID cannot be chosen (the value is that ID).
		needsBricklinkId?: boolean;
		onpick: (part: ProfileCatalogSearchResult) => void;
		// Enter with nothing chosen, given what was typed (an ID, say).
		onenter?: (text: string) => void;
	} = $props();

	let query = $state('');
	let results = $state.raw<ProfileCatalogSearchResult[]>([]);
	let total = $state(0);
	let busy = $state(false);
	let searched = $state(false);
	let failed = $state(false);
	let list = $state<HTMLElement | undefined>();
	let timer: ReturnType<typeof setTimeout> | undefined;
	let latest = 0;
	// Enter pressed before the search came back: pick its first part when it does.
	let pickWhenReady = false;

	function pickable(part: ProfileCatalogSearchResult): boolean {
		return !needsBricklinkId || bricklinkIdsOf(part).length > 0;
	}

	function schedule() {
		clearTimeout(timer);
		const text = query.trim();
		latest += 1;
		pickWhenReady = false;
		if (!text) {
			results = [];
			searched = false;
			busy = false;
			failed = false;
			return;
		}
		busy = true;
		timer = setTimeout(() => void search(text), 250);
	}

	async function search(text: string) {
		const mine = ++latest;
		try {
			const res = await api.searchProfileCatalogParts({ q: text, limit: 12 });
			if (mine !== latest) return;
			results = res.results;
			total = res.total;
			failed = false;
		} catch {
			if (mine !== latest) return;
			results = [];
			total = 0;
			failed = true;
		}
		busy = false;
		searched = true;
		if (pickWhenReady) {
			pickWhenReady = false;
			const first = results.find(pickable);
			if (first) choose(first);
		}
	}

	function choose(part: ProfileCatalogSearchResult) {
		clearTimeout(timer);
		latest += 1;
		query = '';
		results = [];
		searched = false;
		busy = false;
		onpick(part);
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			event.preventDefault();
			const first = results.find(pickable);
			if (onenter) onenter(query.trim());
			else if (first && !busy) choose(first);
			else if (busy) pickWhenReady = true;
		} else if (event.key === 'ArrowDown') {
			event.preventDefault();
			list?.querySelector<HTMLElement>('button')?.focus();
		}
	}

	// Arrow keys walk the results, and Up from the first goes back to the field.
	function onListKey(event: KeyboardEvent) {
		if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
		const buttons = [...(list?.querySelectorAll<HTMLElement>('button') ?? [])];
		const at = buttons.indexOf(document.activeElement as HTMLElement);
		if (at < 0) return;
		event.preventDefault();
		const next = at + (event.key === 'ArrowDown' ? 1 : -1);
		if (next < 0) (list?.previousElementSibling as HTMLElement | null)?.querySelector('input')?.focus();
		else buttons[Math.min(next, buttons.length - 1)]?.focus();
	}
</script>

<div>
	<div class="flex items-center gap-2 pr-2">
		<input
			type="search"
			data-first-value
			aria-label={label}
			{placeholder}
			autocomplete="off"
			bind:value={query}
			oninput={schedule}
			{onkeydown}
			class="h-(--size-control-sm) min-w-0 flex-1 bg-transparent px-2 text-sm text-ink outline-none placeholder:text-ink-faint"
		/>
		{#if busy}<Spinner size={14} class="shrink-0 text-ink-muted" />{/if}
	</div>
	{#if results.length > 0}
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<ul
			bind:this={list}
			onkeydown={onListKey}
			class="max-h-72 divide-y divide-line overflow-y-auto border-t border-line"
		>
			{#each results as part (part.part_num)}
				{@const ids = bricklinkIdsOf(part)}
				{@const ok = pickable(part)}
				<li class="px-2 py-1 {ok ? '' : 'opacity-50'}">
					<PartTile
						padded={false}
						name={part.name}
						imgUrl={part.part_img_url}
						bricklinkId={ids[0] ?? null}
						partNum={part.part_num}
						onclick={ok ? () => choose(part) : undefined}
					/>
					{#if !ok}<p class="pl-15 text-sm text-ink-muted">This part has no BrickLink ID.</p>{/if}
				</li>
			{/each}
		</ul>
		{#if total > results.length}
			<p class="border-t border-line px-3 py-2 text-sm text-ink-muted">
				Showing {results.length} of {total.toLocaleString('en-US')} parts. Type more to narrow them.
			</p>
		{/if}
	{:else if failed}
		<p class="border-t border-line px-3 py-2 text-sm text-danger-ink">The search did not work. Try again.</p>
	{:else if searched && !busy}
		<p class="border-t border-line px-3 py-2 text-sm text-ink-muted">No part matches "{query.trim()}".</p>
	{/if}
</div>

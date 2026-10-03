<!--
	A condition's value when it names a LEGO color or a part category: what is
	chosen sits in the field as chips (a color as its swatch and name), and one
	button opens the catalog's list to choose from, with a search box. "Is one
	of" takes several, and the list stays open while they are ticked; "is" takes
	one, and choosing closes it. The value stored is the catalog's own ID (the
	Rebrickable color, the BrickLink or Rebrickable category), never typed.
-->
<script lang="ts">
	import { tick } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import Plus from '@lucide/svelte/icons/plus';
	import Button from '$lib/components/Button.svelte';
	import ColorChip from '$lib/components/ColorChip.svelte';
	import Input from '$lib/components/Input.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { catalog } from '../catalog.svelte';
	import { toList } from '../fields';
	import ValueBox from './ValueBox.svelte';
	import ValueChip from './ValueChip.svelte';

	type Kind = 'bl_category' | 'rb_category' | 'color';
	type Choice = { id: number; label: string; rgb?: string | null; count?: number | null };

	let {
		kind,
		multi,
		value,
		invalid = false,
		onchange
	}: {
		kind: Kind;
		// "Is one of": several values. Otherwise one.
		multi: boolean;
		value: unknown;
		invalid?: boolean;
		onchange: (value: unknown) => void;
	} = $props();

	const uid = $props.id();
	// More rows than this are a long scroll; the search is how to reach the rest.
	const SHOWN = 120;

	const noun = $derived(kind === 'color' ? 'color' : 'category');
	const nouns = $derived(kind === 'color' ? 'colors' : 'categories');
	const loaded = $derived(
		kind === 'color'
			? catalog.colors.length > 0
			: kind === 'bl_category'
				? catalog.blCategories.length > 0
				: catalog.rbCategories.length > 0
	);

	$effect(() => {
		if (kind === 'color') void catalog.ensureColors();
		else if (kind === 'bl_category') void catalog.ensureBlCategories();
		else void catalog.ensureRbCategories();
	});

	const selected = $derived(
		toList(value)
			.map((v) => Number(v))
			.filter((v) => Number.isFinite(v))
	);

	// A long choice (a dozen categories) folds to its first few chips.
	const FOLDED = 12;
	let unfolded = $state(false);
	const chips = $derived(unfolded ? selected : selected.slice(0, FOLDED));

	// The catalog lists "[Unknown]"; in words it is "Unknown".
	function colorName(name: string): string {
		return name.startsWith('[') ? name.replace(/^\[|\]$/g, '') : name;
	}

	// Every color A to Z with the unknown one last; BrickLink categories that hold
	// no part are left out (nothing could match them) unless one is chosen.
	const choices = $derived.by((): Choice[] => {
		if (kind === 'color') {
			return [...catalog.colors]
				.sort((a, b) => {
					const aUnknown = a.name.startsWith('[');
					const bUnknown = b.name.startsWith('[');
					if (aUnknown !== bUnknown) return aUnknown ? 1 : -1;
					return a.name.localeCompare(b.name);
				})
				.map((c) => ({ id: c.id, label: colorName(c.name), rgb: c.rgb }));
		}
		if (kind === 'bl_category') {
			return catalog.blCategories
				.filter((c) => c.part_count > 0 || selected.includes(c.id))
				.map((c) => ({ id: c.id, label: c.name, count: c.part_count }));
		}
		return catalog.rbCategories.map((c) => ({
			id: c.id,
			label: c.name,
			count: c.actual_part_count ?? c.part_count
		}));
	});

	function choiceFor(id: number): Choice {
		if (kind === 'color') {
			const color = catalog.colorById.get(id);
			return { id, label: color ? colorName(color.name) : `Color ${id}`, rgb: color?.rgb };
		}
		const category = (kind === 'bl_category' ? catalog.blCategoryById : catalog.rbCategoryById).get(id);
		return { id, label: category?.name ?? `Category ${id}` };
	}

	let open = $state(false);
	let query = $state('');
	let highlighted = $state(0);
	let search = $state<HTMLInputElement | undefined>();

	// What was typed, best matches first: the name itself, then names that start
	// with it, then the rest that hold it, each in the list's own order.
	const matches = $derived.by(() => {
		const needle = query.trim().toLowerCase();
		if (!needle) return choices;
		const found: Array<[number, Choice]> = [];
		for (const choice of choices) {
			const label = choice.label.toLowerCase();
			if (label === needle) found.push([0, choice]);
			else if (label.startsWith(needle)) found.push([1, choice]);
			else if (label.includes(needle)) found.push([2, choice]);
		}
		return found.sort((a, b) => a[0] - b[0]).map(([, choice]) => choice);
	});
	const rows = $derived(matches.slice(0, SHOWN));

	$effect(() => {
		if (!open) return;
		query = '';
		highlighted = 0;
		void tick().then(() => search?.focus());
	});

	function pick(id: number) {
		if (multi) {
			onchange(selected.includes(id) ? selected.filter((v) => v !== id) : [...selected, id]);
		} else {
			onchange(id);
			open = false;
		}
	}

	function remove(id: number) {
		onchange(multi ? selected.filter((v) => v !== id) : '');
	}

	function scrollToHighlighted() {
		requestAnimationFrame(() =>
			document.getElementById(`${uid}-option-${highlighted}`)?.scrollIntoView({ block: 'nearest' })
		);
	}

	function onSearchKey(event: KeyboardEvent) {
		if (event.key === 'ArrowDown') highlighted = Math.min(highlighted + 1, rows.length - 1);
		else if (event.key === 'ArrowUp') highlighted = Math.max(highlighted - 1, 0);
		else if (event.key === 'Enter') {
			const row = rows[highlighted];
			if (row) pick(row.id);
		} else return;
		event.preventDefault();
		scrollToHighlighted();
	}

	const triggerLabel = $derived(
		multi
			? selected.length > 0
				? `Add ${nouns}`
				: `Choose ${nouns}`
			: selected.length > 0
				? 'Change'
				: `Choose a ${noun}`
	);
</script>

<ValueBox {invalid} class="flex flex-wrap items-center gap-1 p-1">
	{#each chips as id (id)}
		{@const choice = choiceFor(id)}
		<ValueChip label={choice.label} onremove={() => remove(id)}>
			{#if kind === 'color'}
				<ColorChip name={choice.label} rgb={choice.rgb} />
			{:else}
				<span class="truncate" title={choice.label}>{choice.label}</span>
			{/if}
		</ValueChip>
	{/each}
	{#if selected.length > FOLDED}
		<Button variant="ghost" size="sm" onclick={() => (unfolded = !unfolded)}>
			{unfolded ? 'Show fewer' : `Show all ${selected.length}`}
		</Button>
	{/if}
	<Popover label="Choose {nouns}" placement="bottom-start" width="22rem" padded={false} bind:open>
		{#snippet trigger(props)}
			<Button {...props} data-first-value variant="ghost" size="sm" icon={Plus}>{triggerLabel}</Button>
		{/snippet}
		<div class="flex max-h-96 flex-col">
			<div class="border-b border-line p-2">
				<Input
					bind:element={search}
					bind:value={query}
					type="search"
					size="sm"
					placeholder="Search the {nouns}"
					aria-label="Search the {nouns}"
					aria-controls="{uid}-options"
					aria-activedescendant={rows.length > 0 ? `${uid}-option-${highlighted}` : undefined}
					autocomplete="off"
					oninput={() => (highlighted = 0)}
					onkeydown={onSearchKey}
				/>
			</div>
			<div
				id="{uid}-options"
				role="listbox"
				aria-label={nouns[0].toUpperCase() + nouns.slice(1)}
				aria-multiselectable={multi}
				class="min-h-0 flex-1 overflow-y-auto p-1"
			>
				{#if !loaded}
					<p class="flex items-center gap-2 px-2 py-3 text-ink-muted">
						<Spinner size={14} />{catalog.error ?? `Loading the ${nouns}`}
					</p>
				{:else}
					{#each rows as row, i (row.id)}
						{@const on = selected.includes(row.id)}
						<div
							id="{uid}-option-{i}"
							role="option"
							tabindex="-1"
							aria-selected={on}
							onclick={() => pick(row.id)}
							onkeydown={() => {}}
							onpointermove={() => (highlighted = i)}
							class="flex h-(--size-menu-item) cursor-pointer items-center gap-2 rounded-item pr-3 pl-2 {i ===
							highlighted
								? 'bg-hover'
								: ''}"
						>
							<Check size={16} class="shrink-0 text-primary-ink {on ? '' : 'invisible'}" />
							{#if kind === 'color'}
								<ColorChip name={row.label} rgb={row.rgb} class="flex-1 {on ? 'font-medium' : ''}" />
							{:else}
								<span class="min-w-0 flex-1 truncate {on ? 'font-medium' : ''}">{row.label}</span>
							{/if}
							{#if row.count != null}
								<span class="num shrink-0 text-xs text-ink-faint" title="{row.count} parts">{row.count}</span>
							{/if}
						</div>
					{/each}
					{#if matches.length === 0}
						<p class="px-2 py-3 text-ink-muted">No {noun} matches "{query.trim()}".</p>
					{:else if matches.length > rows.length}
						<p class="px-2 py-2 text-ink-muted">
							Showing {rows.length} of {matches.length}. Type to narrow the list.
						</p>
					{/if}
				{/if}
			</div>
		</div>
	</Popover>
</ValueBox>

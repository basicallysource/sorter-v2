<!--
	One LEGO color, chosen from the catalog: a field that shows the color as
	its swatch and name, and a list on the raised plane with a search box and
	every color as a swatch and name. A piece or a kit line may have no color,
	so the list can open with one row for that (`emptyLabel`, "Any color"), in
	the warning tone when having no color is a thing to be careful about
	(`emptyWarning`). Built like the design system's Select and Hive's
	ModelSelect (a field for a button, the list in the top layer), with the
	search a list of 275 colors needs. The value is the Rebrickable color ID,
	what rule conditions and kit lines use, or null for no color.

	<ColorSelect bind:value={colorId} {colors} emptyLabel="Any color" emptyWarning />
-->
<script lang="ts">
	import type { ProfileCatalogColor } from '$lib/api';
	import { tick } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import ColorChip from '../ColorChip.svelte';
	import { place } from '../place';

	let {
		value = $bindable(null),
		colors,
		emptyLabel = 'Any color',
		emptyWarning = false,
		id,
		label,
		size = 'md',
		disabled = false,
		class: className = '',
		onchange
	}: {
		// The Rebrickable color ID, or null for no color.
		value?: number | null;
		colors: ProfileCatalogColor[];
		// What choosing no color is called.
		emptyLabel?: string;
		emptyWarning?: boolean;
		// For a <label for>; the list gets its own id from it.
		id?: string;
		// The accessible name when no <label> points at it.
		label?: string;
		size?: 'sm' | 'md';
		disabled?: boolean;
		// On a wrapper, so a width set here wins.
		class?: string;
		onchange?: (value: number | null) => void;
	} = $props();

	const uid = $props.id();
	const listId = `${uid}-list`;
	let trigger: HTMLButtonElement;
	let list: HTMLElement;
	let search: HTMLInputElement;
	let open = $state(false);
	let query = $state('');
	let highlighted = $state(0);

	// A to Z by name, with the catalog's "[Unknown]" last.
	const ordered = $derived(
		[...colors].sort((a, b) => {
			const aUnknown = a.name.startsWith('[');
			const bUnknown = b.name.startsWith('[');
			if (aUnknown !== bUnknown) return aUnknown ? 1 : -1;
			return a.name.localeCompare(b.name);
		})
	);

	const chosen = $derived(value === null ? null : (colors.find((c) => c.id === value) ?? null));

	type Row = { id: number | null; name: string; rgb: string | null; bricklink_id?: string };

	// How well a color answers a search: its exact name or BrickLink ID, then a
	// name that starts with it, then a word of the name that does, then any
	// name that holds it.
	function rank(color: ProfileCatalogColor, needle: string): number {
		const name = color.name.toLowerCase();
		if (name === needle || color.bricklink_id === needle) return 0;
		if (name.startsWith(needle)) return 1;
		if (name.split(/[\s-]+/).some((word) => word.startsWith(needle))) return 2;
		if (name.includes(needle) || (color.bricklink_id ?? '').startsWith(needle)) return 3;
		return 4;
	}

	// The rows: the "no color" row first, then the colors that answer the search,
	// the best answers first, each group A to Z.
	const rows = $derived.by((): Row[] => {
		const needle = query.trim().toLowerCase();
		const matches = needle
			? ordered
					.map((color) => ({ color, score: rank(color, needle) }))
					.filter((entry) => entry.score < 4)
					.sort((a, b) => a.score - b.score)
					.map((entry) => entry.color)
			: ordered;
		return [{ id: null, name: emptyLabel, rgb: null }, ...matches];
	});

	// The rows are drawn only while the list is open: a kit has a select on
	// every line, and 275 colors each would be tens of thousands of elements.
	async function ontoggle(event: ToggleEvent) {
		open = event.newState === 'open';
		if (!open) return;
		query = '';
		highlighted = Math.max(
			0,
			rows.findIndex((row) => row.id === value)
		);
		await tick();
		const box = trigger.getBoundingClientRect();
		list.style.width = `${Math.max(box.width, 288)}px`;
		const at = place(box, list.getBoundingClientRect(), 'bottom-start', 4);
		list.style.top = `${at.top}px`;
		list.style.left = `${at.left}px`;
		search.focus();
		scrollToHighlighted();
	}

	function scrollToHighlighted() {
		requestAnimationFrame(() =>
			list.querySelector(`[data-index="${highlighted}"]`)?.scrollIntoView({ block: 'nearest' })
		);
	}

	function choose(row: Row) {
		value = row.id;
		onchange?.(row.id);
		list.hidePopover();
		trigger.focus();
	}

	function onTriggerKey(event: KeyboardEvent) {
		if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
			event.preventDefault();
			list.showPopover();
		}
	}

	function onSearchKey(event: KeyboardEvent) {
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			highlighted = Math.min(highlighted + 1, rows.length - 1);
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			highlighted = Math.max(highlighted - 1, 0);
		} else if (event.key === 'Enter') {
			event.preventDefault();
			const row = rows[highlighted];
			if (row) choose(row);
			return;
		} else if (event.key === 'Tab') {
			list.hidePopover();
			return;
		} else {
			return;
		}
		scrollToHighlighted();
	}
</script>

<div class="relative min-w-0 {className}">
	<button
		bind:this={trigger}
		type="button"
		{id}
		{disabled}
		popovertarget={listId}
		aria-haspopup="listbox"
		aria-expanded={open}
		aria-controls={listId}
		aria-label={label}
		onkeydown={onTriggerKey}
		class="inline-flex w-full min-w-0 items-center justify-between gap-2 rounded-control border bg-field text-left text-sm transition-colors disabled:pointer-events-none disabled:opacity-45
			{open ? 'border-primary outline-2 -outline-offset-1 outline-primary' : 'border-line-strong hover:border-ink-faint'}
			{size === 'sm' ? 'h-(--size-control-sm) pr-2 pl-(--pad-control-sm)' : 'h-(--size-control) pr-2.5 pl-(--pad-control)'}"
	>
		{#if value === null}
			<span
				class="flex min-w-0 items-center gap-1.5 {emptyWarning ? 'text-warning-ink' : 'text-ink-muted'}"
			>
				{#if emptyWarning}<TriangleAlert size={14} class="shrink-0" />{/if}
				<span class="truncate">{emptyLabel}</span>
			</span>
		{:else}
			<ColorChip name={chosen?.name ?? `Color ${value}`} rgb={chosen?.rgb} class="text-ink" />
		{/if}
		<ChevronDown
			size={16}
			class="shrink-0 text-ink-muted transition-transform {open ? 'rotate-180' : ''}"
		/>
	</button>

	<div
		bind:this={list}
		id={listId}
		popover="auto"
		{ontoggle}
		class="fixed inset-auto m-0 max-h-80 max-w-[calc(100vw-1rem)] flex-col overflow-hidden rounded-control border border-line bg-raised text-sm text-ink [&:popover-open]:flex"
	>
		<div class="border-b border-line p-2">
			<input
				bind:this={search}
				bind:value={query}
				oninput={() => (highlighted = query.trim() ? Math.min(1, rows.length - 1) : 0)}
				onkeydown={onSearchKey}
				type="search"
				aria-label="Search the colors"
				aria-controls="{listId}-options"
				placeholder="Search the colors"
				class="h-(--size-control-sm) w-full rounded-control border border-line-strong bg-field px-(--pad-control-sm) text-sm outline-none focus:border-primary"
			/>
		</div>
		<div id="{listId}-options" role="listbox" aria-label={label ?? 'Colors'} class="flex-1 overflow-y-auto p-1">
			{#each open ? rows : [] as row, i (row.id)}
				{@const on = row.id === value}
				<div
					role="option"
					tabindex="-1"
					aria-selected={on}
					data-index={i}
					onclick={() => choose(row)}
					onkeydown={() => {}}
					onpointermove={() => (highlighted = i)}
					class="flex h-(--size-menu-item) cursor-pointer items-center gap-2 rounded-item pr-3 pl-2 {i === highlighted ? 'bg-hover' : ''}"
				>
					<Check size={16} class="shrink-0 text-primary-ink {on ? '' : 'invisible'}" />
					{#if row.id === null}
						<span
							class="flex min-w-0 flex-1 items-center gap-1.5 {emptyWarning ? 'text-warning-ink' : 'text-ink-muted'}"
						>
							{#if emptyWarning}<TriangleAlert size={14} class="shrink-0" />{/if}
							<span class="truncate {on ? 'font-medium' : ''}">{row.name}</span>
						</span>
					{:else}
						<ColorChip name={row.name} rgb={row.rgb} class="flex-1 {on ? 'font-medium' : ''}" />
						{#if row.bricklink_id}
							<span class="num shrink-0 text-xs text-ink-faint" title="BrickLink color {row.bricklink_id}"
								>{row.bricklink_id}</span
							>
						{/if}
					{/if}
				</div>
			{/each}
			{#if open && rows.length === 1 && query.trim()}
				<p class="px-2 py-3 text-ink-muted">No color matches "{query.trim()}".</p>
			{/if}
		</div>
	</div>
</div>

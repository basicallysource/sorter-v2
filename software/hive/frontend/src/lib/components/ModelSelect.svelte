<!--
	The OpenRouter model for the assistant: a Select with a search box, the
	models in groups, and each one's price. Built like the design system's
	Select (a field for a button, the list on the raised plane in the top
	layer), with the search that a list of hundreds of models needs.
-->
<script lang="ts">
	import type { AiModelGroup, AiModelOption } from '$lib/api';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { place } from './place';

	let {
		value = $bindable(),
		groups,
		baselineModel,
		disabled = false,
		id
	}: {
		value: string;
		groups: AiModelGroup[];
		baselineModel?: string;
		disabled?: boolean;
		id?: string;
	} = $props();

	const listId = $derived(`${id ?? 'model'}-list`);
	let trigger: HTMLButtonElement;
	let list: HTMLElement;
	let searchInput: HTMLInputElement;
	let open = $state(false);
	let query = $state('');
	let highlighted = $state(0);

	const allModels = $derived(groups.flatMap((g) => g.models));
	const selected = $derived(allModels.find((m) => m.id === value));
	const filteredGroups = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return groups;
		return groups
			.map((g) => ({
				label: g.label,
				models: g.models.filter((m) => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
			}))
			.filter((g) => g.models.length > 0);
	});
	// The flat order drives the keyboard; the grouped list walks the same order.
	const flatFiltered = $derived(filteredGroups.flatMap((g) => g.models));

	function formatPrice(model: AiModelOption): string | null {
		if (model.input_per_million == null || model.output_per_million == null) return null;
		const fmt = (n: number) => (n < 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(2).replace(/\.00$/, '')}`);
		return `${fmt(model.input_per_million)} in, ${fmt(model.output_per_million)} out, a million tokens`;
	}

	function costTone(model: AiModelOption): string {
		const f = model.cost_factor;
		if (f == null) return 'text-ink-muted';
		if (f <= 0.5) return 'text-success-ink';
		if (f <= 1.5) return 'text-ink-muted';
		return 'text-danger-ink';
	}

	function ontoggle(event: ToggleEvent) {
		open = event.newState === 'open';
		if (!open) return;
		query = '';
		highlighted = Math.max(0, flatFiltered.findIndex((m) => m.id === value));
		const box = trigger.getBoundingClientRect();
		list.style.width = `${Math.max(box.width, 320)}px`;
		const at = place(box, list.getBoundingClientRect(), 'bottom-start', 4);
		list.style.top = `${at.top}px`;
		list.style.left = `${at.left}px`;
		searchInput.focus();
	}

	function choose(model: AiModelOption) {
		value = model.id;
		list.hidePopover();
		trigger.focus();
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			highlighted = Math.min(highlighted + 1, flatFiltered.length - 1);
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			highlighted = Math.max(highlighted - 1, 0);
		} else if (event.key === 'Enter') {
			event.preventDefault();
			const model = flatFiltered[highlighted];
			if (model) choose(model);
		} else {
			return;
		}
		requestAnimationFrame(() =>
			list.querySelector(`[data-index="${highlighted}"]`)?.scrollIntoView({ block: 'nearest' })
		);
	}
</script>

<button
	bind:this={trigger}
	{id}
	type="button"
	{disabled}
	popovertarget={listId}
	aria-haspopup="listbox"
	aria-expanded={open}
	class="inline-flex h-(--size-control) w-full min-w-0 items-center gap-2 rounded-control border bg-field pr-2.5 pl-(--pad-control) text-left text-sm transition-colors disabled:pointer-events-none disabled:opacity-45
		{open ? 'border-primary outline-2 -outline-offset-1 outline-primary' : 'border-line-strong hover:border-ink-faint'}"
>
	<span class="min-w-0 flex-1 truncate font-mono text-ink">{value}</span>
	{#if selected?.cost_factor_label}
		<span class="shrink-0 text-sm {costTone(selected)}">{selected.cost_factor_label}</span>
	{/if}
	<ChevronDown size={16} class="shrink-0 text-ink-muted transition-transform {open ? 'rotate-180' : ''}" />
</button>

<div
	bind:this={list}
	id={listId}
	popover="auto"
	{ontoggle}
	class="fixed inset-auto m-0 max-h-96 max-w-[calc(100vw-1rem)] flex-col overflow-hidden rounded-control border border-line bg-raised text-sm text-ink [&:popover-open]:flex"
>
	<div class="border-b border-line p-2">
		<input
			bind:this={searchInput}
			bind:value={query}
			oninput={() => (highlighted = 0)}
			{onkeydown}
			type="search"
			aria-label="Search the models"
			aria-controls={`${listId}-options`}
			placeholder="Search the models"
			class="h-(--size-control-sm) w-full rounded-control border border-line-strong bg-field px-(--pad-control-sm) text-sm outline-none focus:border-primary"
		/>
	</div>
	<div id={`${listId}-options`} role="listbox" aria-label="Models" class="flex-1 overflow-y-auto p-1">
		{#if flatFiltered.length === 0}
			<p class="p-2 text-ink-muted">No models match "{query}".</p>
		{/if}
		{#each filteredGroups as group (group.label)}
			<div class="label px-2 pt-2 pb-1">{group.label}</div>
			{#each group.models as model (model.id)}
				{@const index = flatFiltered.indexOf(model)}
				<div
					role="option"
					tabindex="-1"
					aria-selected={model.id === value}
					data-index={index}
					onclick={() => choose(model)}
					onkeydown={() => {}}
					onpointermove={() => (highlighted = index)}
					class="flex cursor-pointer items-center gap-2 rounded-item px-2 py-1.5 {index === highlighted ? 'bg-hover' : ''}"
				>
					<Check size={16} class="shrink-0 text-primary-ink {model.id === value ? '' : 'invisible'}" />
					<span class="min-w-0 flex-1">
						<span class="block truncate font-mono text-ink">{model.id}</span>
						{#if formatPrice(model)}<span class="block truncate text-ink-muted">{formatPrice(model)}</span>{/if}
					</span>
					{#if model.cost_factor_label}
						<span class="shrink-0 {costTone(model)}">{model.cost_factor_label}</span>
					{/if}
				</div>
			{/each}
		{/each}
	</div>
	{#if baselineModel}
		<p class="border-t border-line px-3 py-2 text-ink-muted">
			Cost against <span class="font-mono">{baselineModel}</span> (input and output price together), live from
			OpenRouter.
		</p>
	{/if}
</div>

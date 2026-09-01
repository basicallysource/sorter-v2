<script lang="ts">
	import type { AiModelGroup, AiModelOption } from '$lib/api';

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

	let open = $state(false);
	let query = $state('');
	let container = $state<HTMLDivElement | null>(null);
	let searchInput = $state<HTMLInputElement | null>(null);
	let highlighted = $state(0);

	const allModels = $derived(groups.flatMap((g) => g.models));
	const selected = $derived(allModels.find((m) => m.id === value));

	const filteredGroups = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return groups;
		return groups
			.map((g) => ({
				label: g.label,
				models: g.models.filter(
					(m) => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)
				)
			}))
			.filter((g) => g.models.length > 0);
	});

	// Flat order drives keyboard navigation; the grouped render walks the same list.
	const flatFiltered = $derived(filteredGroups.flatMap((g) => g.models));

	function formatPrice(model: AiModelOption): string | null {
		if (model.input_per_million == null || model.output_per_million == null) return null;
		const fmt = (n: number) => (n < 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(2).replace(/\.00$/, '')}`);
		return `${fmt(model.input_per_million)} in / ${fmt(model.output_per_million)} out per M`;
	}

	function costTone(model: AiModelOption): string {
		const f = model.cost_factor;
		if (f == null) return 'text-text-muted';
		if (f <= 0.5) return 'text-success';
		if (f <= 1.5) return 'text-text-muted';
		return 'text-primary';
	}

	function choose(model: AiModelOption) {
		value = model.id;
		open = false;
		query = '';
	}

	function toggle() {
		if (disabled) return;
		open = !open;
		if (open) {
			query = '';
			highlighted = Math.max(0, flatFiltered.findIndex((m) => m.id === value));
			queueMicrotask(() => searchInput?.focus());
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (!open) {
			if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') {
				event.preventDefault();
				toggle();
			}
			return;
		}
		if (event.key === 'Escape') {
			event.preventDefault();
			open = false;
		} else if (event.key === 'ArrowDown') {
			event.preventDefault();
			highlighted = Math.min(highlighted + 1, flatFiltered.length - 1);
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			highlighted = Math.max(highlighted - 1, 0);
		} else if (event.key === 'Enter') {
			event.preventDefault();
			const model = flatFiltered[highlighted];
			if (model) choose(model);
		}
	}

	function handleWindowClick(event: MouseEvent) {
		if (!open || !container) return;
		if (!container.contains(event.target as Node)) open = false;
	}
</script>

<svelte:window onclick={handleWindowClick} />

<div class="relative" bind:this={container}>
	<button
		{id}
		type="button"
		{disabled}
		onclick={toggle}
		onkeydown={handleKeydown}
		aria-haspopup="listbox"
		aria-expanded={open}
		class="flex w-full items-center justify-between gap-3 border border-border bg-surface px-3 py-2 text-left text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
	>
		<span class="min-w-0 flex-1 truncate font-mono text-text">{value}</span>
		{#if selected?.cost_factor_label}
			<span class="shrink-0 text-xs {costTone(selected)}">{selected.cost_factor_label}</span>
		{/if}
		<svg class="h-4 w-4 shrink-0 text-text-muted" viewBox="0 0 20 20" fill="currentColor">
			<path
				fill-rule="evenodd"
				d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
				clip-rule="evenodd"
			/>
		</svg>
	</button>

	{#if open}
		<div
			class="absolute z-30 mt-1 max-h-96 w-full overflow-y-auto border border-border bg-surface shadow-lg"
			role="listbox"
		>
			<div class="sticky top-0 border-b border-border bg-surface p-2">
				<input
					bind:this={searchInput}
					bind:value={query}
					oninput={() => (highlighted = 0)}
					onkeydown={handleKeydown}
					type="text"
					placeholder="Search models..."
					class="w-full border border-border bg-bg px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
				/>
			</div>

			{#if flatFiltered.length === 0}
				<div class="p-3 text-sm text-text-muted">No models match "{query}".</div>
			{/if}

			{#each filteredGroups as group}
				<div class="border-b border-border/50 last:border-b-0">
					<div
						class="bg-bg px-3 py-1 text-xs font-semibold uppercase tracking-wide text-text-muted"
					>
						{group.label}
					</div>
					{#each group.models as model}
						{@const index = flatFiltered.indexOf(model)}
						<button
							type="button"
							role="option"
							aria-selected={model.id === value}
							onclick={() => choose(model)}
							onmouseenter={() => (highlighted = index)}
							class="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-bg
								{index === highlighted ? 'bg-bg' : ''}"
						>
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm text-text">
									{#if model.id === value}<span class="text-primary">✓ </span>{/if}{model.id}
								</span>
								{#if formatPrice(model)}
									<span class="block truncate text-xs text-text-muted">{formatPrice(model)}</span>
								{/if}
							</span>
							{#if model.cost_factor_label}
								<span class="shrink-0 text-xs font-medium {costTone(model)}">
									{model.cost_factor_label}
								</span>
							{/if}
						</button>
					{/each}
				</div>
			{/each}

			{#if baselineModel}
				<div class="border-t border-border bg-bg px-3 py-2 text-xs text-text-muted">
					Cost shown relative to <span class="font-mono">{baselineModel}</span> (blended
					input/output price). Live from OpenRouter.
				</div>
			{/if}
		</div>
	{/if}
</div>

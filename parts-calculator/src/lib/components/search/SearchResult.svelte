<script lang="ts">
	import Highlight from './Highlight.svelte';
	import { KIND_STYLES } from './kinds';
	import type { Hit, SearchItem } from '$lib/search';

	// One row of the palette. Four things, always in the same places: what it
	// looks like, what it is called, what kind of thing it is, and the four
	// characters that would be stamped on it. The uid sits hard right in mono so
	// that scanning down the column while reading an id off a print works — that
	// is the motion the whole palette exists for.
	let {
		id,
		item,
		hit = null,
		active = false,
		onpick,
		onhover
	}: {
		id: string;
		item: SearchItem;
		hit?: Hit | null;
		active?: boolean;
		onpick: () => void;
		onhover?: () => void;
	} = $props();

	const style = $derived(KIND_STYLES[item.kind]);
	const Icon = $derived(style.icon);
	const uid = $derived(item.uid?.toUpperCase() ?? '');
</script>

<button
	{id}
	type="button"
	role="option"
	aria-selected={active}
	class="flex w-full items-center gap-3 border-l-2 px-3 py-2 text-left transition-colors {active
		? 'border-primary bg-primary/[0.06]'
		: 'border-transparent hover:bg-[var(--color-bg)]'}"
	onclick={onpick}
	onmousemove={onhover}
>
	<!-- the render when there is one, the kind's icon when there isn't -->
	<span
		class="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden border border-border bg-[var(--color-bg)] {style.mark}"
	>
		{#if item.image}
			<img src={item.image} alt="" loading="lazy" class="h-full w-full object-contain" />
		{:else}
			<Icon size={16} />
		{/if}
	</span>

	<span class="min-w-0 flex-1">
		<span class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
			<span class="truncate text-sm font-semibold text-text">
				<Highlight text={item.name} range={hit?.name ?? null} />
			</span>
			<span
				class="inline-flex shrink-0 items-center gap-1 border px-1 text-[0.6875rem] font-semibold leading-[1.35] {style.chip}"
			>
				<Icon size={10} />
				{item.label}
				{#if item.note}<span class="font-normal opacity-70">{item.note}</span>{/if}
			</span>
		</span>
		{#if item.subtitle}
			<span class="mt-0.5 block truncate text-xs text-text-muted">{item.subtitle}</span>
		{/if}
	</span>

	{#if uid}
		<span
			class="shrink-0 font-mono text-xs font-semibold tracking-wider {active
				? 'text-text'
				: 'text-text-muted'}"
		>
			<Highlight text={uid} range={hit?.uid ?? null} />
		</span>
	{/if}
</button>

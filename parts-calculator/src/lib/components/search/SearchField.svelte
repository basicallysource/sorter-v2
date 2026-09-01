<script lang="ts">
	import { Search, X } from 'lucide-svelte';
	import { palette } from '$lib/search.svelte';

	// The inline filter that sits above a list. Deliberately plain: it owns
	// nothing but the text, and the page it lives on decides what that text
	// filters, ranking through the same matcher the palette uses.
	//
	// It also knows one thing about the palette: a list filter can only ever
	// narrow the list it is attached to, so when what you typed finds nothing —
	// or when you want the whole catalog rather than this page's slice — it hands
	// the query over to the palette instead of leaving you at a dead end.
	let {
		value = $bindable(''),
		placeholder = 'Filter…',
		label,
		/** How many rows survive the filter, and how many there were. */
		found = null,
		total = null,
		noun = 'result',
		nouns = '',
		wide = false,
		class: cls = ''
	}: {
		value?: string;
		placeholder?: string;
		label: string;
		found?: number | null;
		total?: number | null;
		noun?: string;
		/** Plural of `noun`, when adding an s is wrong ("match" → "matches"). */
		nouns?: string;
		/** Let the input grow with its container instead of capping at max-w-xs. */
		wide?: boolean;
		class?: string;
	} = $props();

	const plural = $derived(nouns || `${noun}s`);
	let input = $state<HTMLInputElement | null>(null);
	const filtering = $derived(value.trim().length > 0);
	const empty = $derived(filtering && found === 0);

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape' && value) {
			// Clear before closing anything else — the field is what has focus.
			e.stopPropagation();
			value = '';
		}
	}
</script>

<div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 {cls}">
	<div class="relative min-w-0 flex-1 {wide ? '' : 'sm:max-w-xs'}">
		<span class="pointer-events-none absolute inset-y-0 left-0 flex w-8 items-center justify-center text-text-muted">
			<Search size={14} />
		</span>
		<input
			bind:this={input}
			bind:value
			onkeydown={onKey}
			type="search"
			spellcheck="false"
			autocomplete="off"
			aria-label={label}
			{placeholder}
			class="setup-control h-9 w-full min-h-0 pl-8 pr-8 text-sm"
		/>
		{#if filtering}
			<button
				type="button"
				class="absolute inset-y-0 right-0 flex w-8 items-center justify-center text-text-muted hover:text-text"
				onclick={() => {
					value = '';
					input?.focus();
				}}
				aria-label="Clear the filter"
			>
				<X size={14} />
			</button>
		{/if}
	</div>

	{#if filtering && found !== null}
		<span class="text-xs text-text-muted" aria-live="polite">
			{#if empty}
				Nothing here matches <span class="font-semibold text-text">{value}</span>.
			{:else}
				{found}{#if total !== null}<span class="text-text-muted">/{total}</span>{/if}
				{found === 1 ? noun : plural}
			{/if}
		</span>
	{/if}

	{#if filtering}
		<button
			type="button"
			class="text-xs font-semibold text-primary hover:text-primary-hover"
			onclick={() => palette.show(value)}
		>
			Search everything for “{value}” →
		</button>
	{/if}
</div>

<style>
	/* `type="search"` is right semantically, but the browser draws its own clear
	   button for it — next to ours, which is styled and sits where the layout
	   expects. Two Xs in one field is just a bug you can see. */
	input[type='search']::-webkit-search-cancel-button,
	input[type='search']::-webkit-search-decoration {
		appearance: none;
		display: none;
	}
</style>

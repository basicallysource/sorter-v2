<script lang="ts">
	import { onMount } from 'svelte';
	import { Search } from 'lucide-svelte';
	import Kbd from './Kbd.svelte';
	import { isMacKeyboard, palette } from '$lib/search.svelte';

	// The way in, in the header. Reads as a search box rather than a button
	// because that is what it replaces and what people aim at, and it carries the
	// shortcut so the shortcut is discoverable rather than folklore.
	// On a phone the header is logo + this + the menu, and the word "Search" costs
	// the logo more room than it is worth next to a magnifier.
	let { class: cls = '', compact = false }: { class?: string; compact?: boolean } = $props();

	// The site is prerendered, so the shipped HTML can't know whose keyboard it
	// lands on. Decide after mount and show nothing rather than the wrong key.
	let mac = $state<boolean | null>(null);
	onMount(() => (mac = isMacKeyboard()));
</script>

<button
	type="button"
	class="setup-control flex h-8 min-h-0 items-center gap-2 px-2 text-sm text-text-muted transition-colors hover:text-text {cls}"
	onclick={() => palette.show()}
	aria-label="Search the catalog"
	aria-keyshortcuts="Meta+K Control+K"
	title={compact ? 'Search the catalog' : undefined}
>
	<Search size={compact ? 16 : 14} class="shrink-0" />
	{#if !compact}<span class="pr-1">Search</span>{/if}
	{#if !compact && mac !== null}
		<span class="ml-auto hidden items-center gap-0.5 md:flex">
			<Kbd>{mac ? '⌘' : 'Ctrl'}</Kbd><Kbd>K</Kbd>
		</span>
	{/if}
</button>

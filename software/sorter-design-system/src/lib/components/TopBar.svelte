<!--
	docs/layout.md#top-bar. The first level of an app's navigation: the mark,
	the app's pages, and on the right what applies everywhere (the machine,
	its status, the theme). It is a surface and owns the one line under it;
	nothing below it draws a line at its top. The current page's 2px primary
	mark sits on that line, replacing it.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';

	type Item = { href: string; label: string };

	let { items, brand, end }: { items: Item[]; brand: Snippet; end?: Snippet } = $props();

	const current = $derived(
		items
			.filter((i) =>
				i.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(i.href)
			)
			.sort((a, b) => b.href.length - a.href.length)[0]?.href
	);
</script>

<header class="sticky top-0 z-30 border-b border-line bg-surface">
	<div class="flex h-12 items-center gap-6 px-4 sm:px-6">
		<div class="flex shrink-0 items-center">{@render brand()}</div>
		<nav aria-label="Main" class="flex h-full min-w-0 items-stretch gap-5 overflow-x-auto">
			{#each items as item (item.href)}
				{@const on = item.href === current}
				<a
					href={item.href}
					aria-current={on ? 'page' : undefined}
					class="relative -mb-px flex items-center text-sm whitespace-nowrap transition-colors
						{on
						? 'font-medium text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-primary'
						: 'text-ink-muted hover:text-ink'}"
				>
					{item.label}
				</a>
			{/each}
		</nav>
		{#if end}<div class="ml-auto flex shrink-0 items-center gap-2">{@render end()}</div>{/if}
	</div>
</header>

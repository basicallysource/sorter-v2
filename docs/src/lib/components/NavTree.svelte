<script lang="ts">
	import NavTree from './NavTree.svelte';
	import type { NavItem } from '$lib/server/content';

	let { items, currentUrl }: { items: NavItem[]; currentUrl: string } = $props();
</script>

<ul class="nav-tree">
	{#each items as item (item.url)}
		<li>
			<a href={item.url} aria-current={item.url === currentUrl ? 'page' : undefined}>
				{item.title}
			</a>
			{#if item.children}
				<NavTree items={item.children} {currentUrl} />
			{/if}
		</li>
	{/each}
</ul>

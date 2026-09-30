<!--
	docs/layout.md#side-nav. The second level of an app's navigation (the
	settings pages): a column on the surface plane, the full height beside
	the content, which sits on the canvas. No line between them: their fills
	differ. The current page takes the primary tint; a group's name is a label.
-->
<script lang="ts">
	import type { Component } from 'svelte';
	import { page } from '$app/state';

	type Item = {
		href: string;
		label: string;
		icon?: Component<{ size?: number; class?: string }>;
		// Something to read at a glance: a count or a short status.
		meta?: string;
	};
	type Group = { label?: string; items: Item[] };

	let { groups, label = 'Sections' }: { groups: Group[]; label?: string } = $props();

	// The deepest item whose href the path starts with is the current one.
	const current = $derived(
		groups
			.flatMap((g) => g.items)
			.filter((i) => page.url.pathname === i.href || page.url.pathname.startsWith(i.href + '/'))
			.sort((a, b) => b.href.length - a.href.length)[0]?.href
	);
</script>

<nav aria-label={label} class="flex flex-col gap-5">
	{#each groups as group, g (g)}
		<div class="flex flex-col gap-px">
			{#if group.label}<div class="label px-2.5 pb-1.5">{group.label}</div>{/if}
			{#each group.items as item (item.href)}
				{@const on = item.href === current}
				<a
					href={item.href}
					aria-current={on ? 'page' : undefined}
					class="flex h-(--size-nav-item) items-center gap-2.5 rounded-item px-2.5 text-sm transition-colors
						{on
						? 'bg-primary-soft font-medium text-primary-ink'
						: 'text-ink-muted hover:bg-hover hover:text-ink'}"
				>
					{#if item.icon}<item.icon size={16} class="shrink-0" />{/if}
					<span class="min-w-0 flex-1 truncate">{item.label}</span>
					{#if item.meta}<span class="num text-xs text-ink-faint">{item.meta}</span>{/if}
				</a>
			{/each}
		</div>
	{/each}
</nav>

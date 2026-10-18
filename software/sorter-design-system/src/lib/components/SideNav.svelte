<!--
	docs/layout.md#side-nav. The second level of an app's navigation (the
	settings pages): a column on the surface plane, the full height beside
	the content, which sits on the canvas. No line between them: their fills
	differ. The current page takes the primary tint; a group's name is a label.

	An item can have sub-tabs (`children`): pages that belong to it, listed
	indented under it, always, so no one has to open an item to find one and
	the column never changes height as someone moves through it. The item is
	the first view of its own pages and is not repeated in the list. A sub-tab
	has no icon; its name lines up with its item's name. Only the deepest page
	the address is on takes the tint; its item, above it, goes to full ink.
-->
<script lang="ts">
	import type { Component } from 'svelte';
	import { page } from '$app/state';

	type Child = {
		href: string;
		label: string;
		// Something to read at a glance: a count or a short status.
		meta?: string;
	};
	type Item = Child & {
		icon?: Component<{ size?: number; class?: string }>;
		children?: Child[];
	};
	type Group = { label?: string; items: Item[] };

	let { groups, label = 'Sections' }: { groups: Group[]; label?: string } = $props();

	// The deepest page whose href the path starts with is the current one.
	const current = $derived(
		groups
			.flatMap((g) => g.items.flatMap((i) => [i, ...(i.children ?? [])]))
			.filter((i) => page.url.pathname === i.href || page.url.pathname.startsWith(i.href + '/'))
			.sort((a, b) => b.href.length - a.href.length)[0]?.href
	);

	const row = 'flex h-(--size-nav-item) items-center rounded-item text-sm transition-colors';
	const tone = (on: boolean, open = false) =>
		on
			? 'bg-primary-soft font-medium text-primary-ink'
			: `${open ? 'text-ink' : 'text-ink-muted'} hover:bg-hover hover:text-ink`;
</script>

<nav aria-label={label} class="flex flex-col gap-5">
	{#each groups as group, g (g)}
		<div class="flex flex-col gap-px">
			{#if group.label}<div class="label px-2.5 pb-1.5">{group.label}</div>{/if}
			{#each group.items as item (item.href)}
				{@const on = item.href === current}
				{@const open = item.children?.some((c) => c.href === current) ?? false}
				<a
					href={item.href}
					aria-current={on ? 'page' : undefined}
					class="{row} gap-2.5 px-2.5 {tone(on, open)}"
				>
					{#if item.icon}<item.icon size={16} class="shrink-0" />{/if}
					<span class="min-w-0 flex-1 truncate">{item.label}</span>
					{#if item.meta}<span class="num text-xs text-ink-faint">{item.meta}</span>{/if}
				</a>
				{#each item.children ?? [] as child (child.href)}
					{@const onChild = child.href === current}
					<a
						href={child.href}
						aria-current={onChild ? 'page' : undefined}
						class="{row} gap-2.5 pr-2.5 {item.icon ? 'pl-9' : 'pl-5'} {tone(onChild)}"
					>
						<span class="min-w-0 flex-1 truncate">{child.label}</span>
						{#if child.meta}<span class="num text-xs text-ink-faint">{child.meta}</span>{/if}
					</a>
				{/each}
			{/each}
		</div>
	{/each}
</nav>

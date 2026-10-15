<!--
	docs/components.md#tabs. Views of one thing, inside a page or a panel.
	The bar owns the line under it, and the chosen tab's primary mark (as
	wide as the tab, --indicator thick) sits on that line, replacing it, so
	the two never stack. The line is the outer element's; the tabs sit one
	pixel over it in a box of their own that scrolls sideways, without a
	scroll bar, when they do not fit. (A mark pushed out of the scrolling box
	itself is clipped, and gives the box a scroll bar.) Pages of the app are
	the TopBar's or the SideNav's, not tabs.

	With an `href` on every item the tabs are links: each view has an address
	of its own, so Back and a bookmark work, and the app marks the current one
	with `value`. The bar is then a `nav` of links (the current one has
	`aria-current`), not a tablist; Tab moves between them.
-->
<script lang="ts" generics="T extends string">
	type Item = { value: T; label: string; count?: number; href?: string };

	let {
		value = $bindable(),
		items,
		label,
		inset = false,
		onchange
	}: {
		value: T;
		items: Item[];
		// The accessible name of the tab list.
		label: string;
		// Indent the tabs to a panel's padding (use at the top of a flush Panel).
		inset?: boolean;
		onchange?: (value: T) => void;
	} = $props();

	const links = $derived(items.length > 0 && items.every((i) => i.href));

	function choose(next: T) {
		value = next;
		onchange?.(next);
	}

	function onkeydown(event: KeyboardEvent) {
		const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
		if (!step) return;
		event.preventDefault();
		const index = items.findIndex((i) => i.value === value);
		const next = items[(index + step + items.length) % items.length];
		choose(next.value);
		(event.currentTarget as HTMLElement)
			.querySelector<HTMLElement>(`[data-value="${next.value}"]`)
			?.focus();
	}

	const box = $derived(
		`-mb-px flex gap-1 overflow-x-auto [scrollbar-width:none] ${
			inset ? 'px-[calc(var(--pad-panel)-0.75rem)]' : ''
		}`
	);

	function tab(on: boolean) {
		return `relative inline-flex h-(--size-tab) items-center gap-2 px-3 text-sm whitespace-nowrap transition-colors ${
			on
				? 'font-medium text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-(--indicator) after:bg-primary'
				: 'text-ink-muted hover:text-ink'
		}`;
	}
</script>

{#snippet body(item: Item)}
	{item.label}
	{#if item.count !== undefined}
		<span class="num text-xs text-ink-muted">{item.count}</span>
	{/if}
{/snippet}

<div class="border-b border-line">
	{#if links}
		<nav aria-label={label} class={box}>
			{#each items as item (item.value)}
				{@const on = item.value === value}
				<a href={item.href} aria-current={on ? 'page' : undefined} class={tab(on)}>
					{@render body(item)}
				</a>
			{/each}
		</nav>
	{:else}
		<div role="tablist" aria-label={label} tabindex="-1" {onkeydown} class={box}>
			{#each items as item (item.value)}
				{@const on = item.value === value}
				<button
					type="button"
					role="tab"
					aria-selected={on}
					tabindex={on ? 0 : -1}
					data-value={item.value}
					onclick={() => choose(item.value)}
					class={tab(on)}
				>
					{@render body(item)}
				</button>
			{/each}
		</div>
	{/if}
</div>

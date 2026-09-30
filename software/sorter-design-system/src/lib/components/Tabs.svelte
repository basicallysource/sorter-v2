<!--
	docs/components.md#tabs. Views of one thing, inside a page or a panel.
	The bar owns the line under it, and the chosen tab's primary mark (as
	wide as the tab, --indicator thick) sits on that line, replacing it, so
	the two never stack. Pages of the
	app are the TopBar's or the SideNav's, not tabs.
-->
<script lang="ts" generics="T extends string">
	type Item = { value: T; label: string; count?: number };

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
</script>

<div
	role="tablist"
	aria-label={label}
	tabindex="-1"
	{onkeydown}
	class="flex gap-1 overflow-x-auto border-b border-line {inset
		? 'px-[calc(var(--pad-panel)-0.75rem)]'
		: ''}"
>
	{#each items as item (item.value)}
		{@const on = item.value === value}
		<button
			type="button"
			role="tab"
			aria-selected={on}
			tabindex={on ? 0 : -1}
			data-value={item.value}
			onclick={() => choose(item.value)}
			class="relative -mb-px inline-flex h-(--size-tab) items-center gap-2 px-3 text-sm whitespace-nowrap transition-colors
				{on
				? 'font-medium text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-(--indicator) after:bg-primary'
				: 'text-ink-muted hover:text-ink'}"
		>
			{item.label}
			{#if item.count !== undefined}
				<span class="num text-xs text-ink-muted">{item.count}</span>
			{/if}
		</button>
	{/each}
</div>

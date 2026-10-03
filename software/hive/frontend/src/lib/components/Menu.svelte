<!--
	docs/overlays.md#menu. Actions or links that open from a button: the
	machine's menu, a card's "more" menu, a profile switcher. It floats,
	so it is the raised plane, like a Popover: a fill and one line, no shadow. The arrow keys move through the
	items, Enter chooses, Escape or a click outside closes it, and focus goes
	back to the button. An item that destroys something goes last, after a
	separator, in danger ink, and its action asks for confirmation (Modal).
	A group (`{ group: 'Admin', items: [...] }`) puts its name over its items,
	as a label; a link that is `checked` is the current page.

	The button that opens a menu shows three dots (`ellipsis`) and a name, never
	the icon of one of the actions inside (docs/icons.md).

	<Menu label="Machine" items={[...]}>
		{#snippet trigger(props)}<Button {...props} icon={Ellipsis} label="Machine" />{/snippet}
	</Menu>
-->
<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import { place, type Placement } from './place';

	type Action = {
		label: string;
		icon?: Component<{ size?: number; class?: string }>;
		// What it does. Or `href` to go somewhere.
		onselect?: () => void;
		href?: string;
		// A short fact to the right: a shortcut, a count.
		hint?: string;
		// A choice in a switcher: the current one gets a check.
		checked?: boolean;
		danger?: boolean;
		disabled?: boolean;
	};
	type Group = { group: string; items: (Action | 'separator')[] };
	type Item = Action | Group | 'separator';

	type TriggerProps = {
		popovertarget: string;
		'aria-expanded': boolean;
		'aria-haspopup': 'menu';
	};

	let {
		items,
		trigger,
		label,
		placement = 'bottom-end',
		width = '15rem'
	}: {
		items: Item[];
		trigger: Snippet<[TriggerProps]>;
		// The menu's accessible name.
		label: string;
		placement?: Placement;
		width?: string;
	} = $props();

	const uid = $props.id();
	const id = `${uid}-menu`;
	let anchor: HTMLElement;
	let panel: HTMLElement;
	let open = $state(false);

	const actions = $derived(
		items
			.flatMap((i) => (i !== 'separator' && 'group' in i ? i.items : [i]))
			.filter((i): i is Action => i !== 'separator')
	);
	const hasChecks = $derived(actions.some((i) => i.checked !== undefined));

	function entries(): HTMLElement[] {
		return [
			...panel.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([aria-disabled="true"])')
		];
	}

	function ontoggle(event: ToggleEvent) {
		open = event.newState === 'open';
		if (!open) return;
		const at = place(anchor.getBoundingClientRect(), panel.getBoundingClientRect(), placement);
		panel.style.top = `${at.top}px`;
		panel.style.left = `${at.left}px`;
		entries()[0]?.focus();
	}

	function onkeydown(event: KeyboardEvent) {
		const list = entries();
		const at = list.indexOf(document.activeElement as HTMLElement);
		const to: Record<string, number> = {
			ArrowDown: (at + 1) % list.length,
			ArrowUp: (at - 1 + list.length) % list.length,
			Home: 0,
			End: list.length - 1
		};
		if (event.key in to) {
			event.preventDefault();
			list[to[event.key]]?.focus();
		} else if (event.key === 'Tab') {
			panel.hidePopover();
		}
	}

	function choose(item: Action) {
		if (item.disabled) return;
		panel.hidePopover();
		item.onselect?.();
	}
</script>

{#snippet action(item: Action)}
	{@const classes = `flex h-(--size-menu-item) w-full items-center gap-2.5 rounded-item px-2.5 text-left outline-none focus-visible:bg-hover hover:bg-hover ${
		item.disabled ? 'pointer-events-none opacity-45' : ''
	} ${item.danger ? 'text-danger-ink' : 'text-ink'}`}
	{#snippet body()}
		{#if hasChecks}
			<Check size={16} class="shrink-0 {item.checked ? '' : 'invisible'}" />
		{/if}
		{#if item.icon}<item.icon size={16} class="shrink-0" />{/if}
		<span class="min-w-0 flex-1 truncate">{item.label}</span>
		{#if item.hint}<span class="num shrink-0 text-xs text-ink-faint">{item.hint}</span>{/if}
	{/snippet}
	{#if item.href && !item.disabled}
		<a
			href={item.href}
			role="menuitem"
			tabindex="-1"
			aria-current={item.checked ? 'page' : undefined}
			class={classes}
			onclick={() => panel.hidePopover()}>{@render body()}</a
		>
	{:else}
		<button
			type="button"
			role={item.checked === undefined ? 'menuitem' : 'menuitemradio'}
			aria-checked={item.checked}
			aria-disabled={item.disabled || undefined}
			tabindex="-1"
			class={classes}
			onclick={() => choose(item)}>{@render body()}</button
		>
	{/if}
{/snippet}

<span bind:this={anchor} class="inline-flex">
	{@render trigger({ popovertarget: id, 'aria-expanded': open, 'aria-haspopup': 'menu' })}
</span>

<div
	bind:this={panel}
	{id}
	popover="auto"
	role="menu"
	aria-label={label}
	tabindex="-1"
	{ontoggle}
	{onkeydown}
	style:width
	class="fixed inset-auto m-0 max-w-[calc(100vw-1rem)] rounded-control border border-line bg-raised p-1 text-sm text-ink"
>
	{#each items as item, i (i)}
		{#if item === 'separator'}
			<div role="separator" class="-mx-1 my-1 h-px bg-line"></div>
		{:else if 'group' in item}
			<div role="group" aria-labelledby="{uid}-group-{i}">
				<div id="{uid}-group-{i}" class="label px-2.5 pt-1.5 pb-1">{item.group}</div>
				{#each item.items as entry, j (j)}
					{#if entry === 'separator'}
						<div role="separator" class="-mx-1 my-1 h-px bg-line"></div>
					{:else}
						{@render action(entry)}
					{/if}
				{/each}
			</div>
		{:else}
			{@render action(item)}
		{/if}
	{/each}
</div>

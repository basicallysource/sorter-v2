<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Anchored } from '$lib/popover';

	// Click-to-open menu in the site style. Unlike Popover (hover-to-peek
	// context help), this is a control: it opens on click only, and the content
	// snippet gets `close` so picking an item can dismiss it.
	//
	// The menu itself is drawn in the shared floating layer, so it is not cut off
	// by whatever the trigger happens to sit inside and nothing on the page can
	// be painted over it.
	let {
		label,
		placement = 'bottom-end',
		menuClass = 'w-56',
		trigger,
		children
	}: {
		label: string;
		placement?: 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end';
		menuClass?: string;
		trigger: Snippet<[{ toggle: () => void; open: boolean }]>;
		children: Snippet<[{ close: () => void }]>;
	} = $props();

	let open = $state(false);
	let root = $state<HTMLElement | null>(null);
	const toggle = () => (open = !open);
	const close = () => (open = false);
</script>

<span bind:this={root} class="relative inline-flex align-middle">
	{@render trigger({ toggle, open })}
</span>

{#if open}
	<Anchored
		anchor={root}
		{placement}
		class="setup-panel {menuClass} py-1"
		onDismiss={close}
	>
		<div role="menu" aria-label={label}>{@render children({ close })}</div>
	</Anchored>
{/if}

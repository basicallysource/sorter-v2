<script lang="ts">
	import type { Snippet } from 'svelte';

	// Click-to-open menu in the site style. Unlike Popover (hover-to-peek
	// context help), this is a control: it opens on click only, and the content
	// snippet gets `close` so picking an item can dismiss it.
	let {
		label,
		align = 'right',
		menuClass = 'w-56',
		trigger,
		children
	}: {
		label: string;
		align?: 'left' | 'right';
		menuClass?: string;
		trigger: Snippet<[{ toggle: () => void; open: boolean }]>;
		children: Snippet<[{ close: () => void }]>;
	} = $props();

	let open = $state(false);
	let root: HTMLElement;
	const toggle = () => (open = !open);
	const close = () => (open = false);

	function onWindowClick(e: MouseEvent) {
		if (open && root && !root.contains(e.target as Node)) open = false;
	}
	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') open = false;
	}
</script>

<svelte:window onclick={onWindowClick} onkeydown={onKey} />

<span bind:this={root} class="relative inline-flex align-middle">
	{@render trigger({ toggle, open })}
	{#if open}
		<div
			class="setup-panel absolute top-full z-30 mt-1 {menuClass} py-1 {align === 'right'
				? 'right-0'
				: 'left-0'}"
			role="menu"
			aria-label={label}
		>
			{@render children({ close })}
		</div>
	{/if}
</span>

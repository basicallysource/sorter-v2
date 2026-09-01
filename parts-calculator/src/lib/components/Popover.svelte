<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Info } from 'lucide-svelte';

	// Generic click-to-open context popover. Reuse anywhere you need an inline
	// explanation. Provide content via the `text` prop or a `children` snippet,
	// and (optionally) a custom trigger via the `trigger` snippet.
	let {
		text = '',
		label = 'More information',
		align = 'left',
		width = 'w-64',
		children,
		trigger
	}: {
		text?: string;
		label?: string;
		align?: 'left' | 'right';
		width?: string;
		children?: Snippet;
		trigger?: Snippet<[{ toggle: () => void; open: boolean }]>;
	} = $props();

	// Open on hover; click "pins" it open (so it survives on touch / after the
	// pointer leaves). Visible whenever hovered or pinned.
	let hovered = $state(false);
	let pinned = $state(false);
	const open = $derived(hovered || pinned);
	let root: HTMLElement;
	const toggle = () => (pinned = !pinned);

	function onWindowClick(e: MouseEvent) {
		if (pinned && root && !root.contains(e.target as Node)) pinned = false;
	}
	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			pinned = false;
			hovered = false;
		}
	}
</script>

<svelte:window onclick={onWindowClick} onkeydown={onKey} />

<span
	bind:this={root}
	class="relative inline-flex align-middle"
	onmouseenter={() => (hovered = true)}
	onmouseleave={() => (hovered = false)}
	onfocusin={() => (hovered = true)}
	onfocusout={() => (hovered = false)}
	role="presentation"
>
	{#if trigger}
		{@render trigger({ toggle, open })}
	{:else}
		<button
			type="button"
			class="inline-flex text-text-muted transition-colors hover:text-text"
			aria-label={label}
			aria-expanded={open}
			onclick={toggle}
		>
			<Info size={14} />
		</button>
	{/if}

	{#if open}
		<div
			class="setup-panel absolute top-6 z-30 {width} p-3 text-sm font-normal normal-case tracking-normal text-text-muted {align ===
			'right'
				? 'right-0'
				: 'left-0'}"
			role="tooltip"
		>
			{#if children}{@render children()}{:else}{text}{/if}
		</div>
	{/if}
</span>

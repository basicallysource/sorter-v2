<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		text,
		class: className = '',
		children
	}: {
		text: string;
		class?: string;
		children: Snippet;
	} = $props();

	let visible = $state(false);
	let trigger: HTMLElement | undefined = $state();
	let style = $state('');

	// position: fixed escapes overflow-hidden/scroll ancestors (the absolute
	// variant got clipped inside scrollable sidebars). Clamp horizontally so
	// the bubble never leaves the viewport.
	const HALF_MAX_WIDTH = 140;

	function show() {
		if (!trigger) return;
		const rect = trigger.getBoundingClientRect();
		const center = Math.min(
			Math.max(rect.left + rect.width / 2, HALF_MAX_WIDTH + 8),
			window.innerWidth - HALF_MAX_WIDTH - 8
		);
		style = `left:${Math.round(center)}px; top:${Math.round(rect.top - 4)}px;`;
		visible = true;
	}

	function hide() {
		visible = false;
	}
</script>

<span
	bind:this={trigger}
	class="relative inline-flex {className}"
	onmouseenter={show}
	onmouseleave={hide}
	onfocusin={show}
	onfocusout={hide}
	role="presentation"
>
	{@render children()}
	{#if visible && text}
		<span
			class="pointer-events-none fixed z-50 max-w-[280px] -translate-x-1/2 -translate-y-full border border-border bg-surface px-2 py-1 text-xs text-text shadow-md"
			{style}
			role="tooltip"
		>
			{text}
		</span>
	{/if}
</span>

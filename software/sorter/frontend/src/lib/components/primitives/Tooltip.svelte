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

	function show() {
		visible = true;
	}

	function hide() {
		visible = false;
	}
</script>

<span
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
			class="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1 -translate-x-1/2 whitespace-nowrap border border-border bg-surface px-2 py-1 text-xs text-text shadow-md"
			role="tooltip"
		>
			{text}
		</span>
	{/if}
</span>

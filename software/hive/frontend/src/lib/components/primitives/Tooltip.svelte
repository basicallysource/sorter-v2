<script lang="ts">
	import type { Snippet } from 'svelte';

	type Placement = 'top' | 'bottom' | 'left' | 'right';

	interface Props {
		text: string;
		placement?: Placement;
		children: Snippet;
	}

	let { text, placement = 'top', children }: Props = $props();

	let visible = $state(false);

	const PLACEMENTS: Record<Placement, string> = {
		top: 'bottom-full left-1/2 mb-2 -translate-x-1/2',
		bottom: 'top-full left-1/2 mt-2 -translate-x-1/2',
		left: 'right-full top-1/2 mr-2 -translate-y-1/2',
		right: 'left-full top-1/2 ml-2 -translate-y-1/2',
	};

	function show() {
		visible = true;
	}
	function hide() {
		visible = false;
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span
	class="relative inline-flex"
	onmouseenter={show}
	onmouseleave={hide}
	onfocusin={show}
	onfocusout={hide}
>
	{@render children()}
	{#if visible}
		<span
			role="tooltip"
			class="pointer-events-none absolute z-50 whitespace-nowrap bg-text px-2 py-1 text-xs text-surface shadow-md {PLACEMENTS[placement]}"
		>
			{text}
		</span>
	{/if}
</span>

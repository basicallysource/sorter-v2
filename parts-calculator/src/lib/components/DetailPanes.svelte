<script lang="ts">
	import type { Snippet } from 'svelte';

	// The detail views' shared frame — THE one layout for any detail that leads
	// with a visual. In a modal the visual and the facts sit side by side once
	// there's room: visual pinned left at 55%, facts scrolling on the right;
	// stacked on narrow screens. On a standalone page everything just flows.
	// PartDetail and LasercutDetail both render through this; a new visual-led
	// detail view uses it rather than laying out its own panes.
	let {
		variant = 'modal',
		visual,
		facts
	}: {
		variant?: 'modal' | 'page';
		visual: Snippet;
		facts: Snippet;
	} = $props();
</script>

<div class={variant === 'modal' ? 'flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row' : ''}>
	<div class="relative {variant === 'modal' ? 'shrink-0 lg:w-[55%]' : ''}">
		{@render visual()}
	</div>
	<!-- in the modal the facts scroll independently of the pinned visual (which
	     owns wheel = zoom); on the page everything just flows -->
	<div class="{variant === 'modal' ? 'min-h-0 flex-1 overflow-y-auto border-t lg:border-l lg:border-t-0' : 'border-t'} border-border">
		{@render facts()}
	</div>
</div>

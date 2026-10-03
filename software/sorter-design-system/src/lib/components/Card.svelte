<!--
	docs/components.md#panels. A panel that is one thing to open: a machine,
	a profile. The whole card is the target: a link (`href`) or a button
	(`onclick`) laid under its content and named by `label`. The pointer
	anywhere on it fills it a step, as any state is shown: never a shadow, a
	lift or a heavier line. Links and buttons inside the card still work (a
	machine's own page, a menu), and each is its own stop for Tab after the
	card.

	<Card href="/machines/{machine.id}" label={machine.name}>...</Card>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		href,
		onclick,
		label,
		padded = true,
		class: className = '',
		children
	}: {
		href?: string;
		onclick?: (event: MouseEvent) => void;
		// What opening it does or where it goes, for a screen reader: its title.
		label: string;
		// False for content that runs to the card's edges (a picture, a grid of stats).
		padded?: boolean;
		class?: string;
		children: Snippet;
	} = $props();

	const target =
		'absolute inset-0 rounded-panel transition-colors hover:bg-hover active:bg-pressed';
</script>

<div class="relative isolate flex flex-col rounded-panel bg-surface {className}">
	{#if href}
		<a {href} aria-label={label} class={target}></a>
	{:else}
		<button type="button" aria-label={label} {onclick} class={target}></button>
	{/if}
	<!-- The content lets the pointer through to the target, except its own controls. -->
	<div
		class="pointer-events-none relative flex min-h-0 flex-1 flex-col [&_a]:pointer-events-auto [&_button]:pointer-events-auto [&_input]:pointer-events-auto [&_label]:pointer-events-auto [&_select]:pointer-events-auto [&_summary]:pointer-events-auto [&_textarea]:pointer-events-auto {padded
			? 'p-(--pad-panel)'
			: ''}"
	>
		{@render children()}
	</div>
</div>

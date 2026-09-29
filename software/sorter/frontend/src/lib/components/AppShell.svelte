<!--
	The app's frame: the header, and under it the page on the canvas
	(software/sorter-design-system/docs/layout.md). With `fit`, from lg up
	the screen is exactly the window and the page never scrolls because of
	the header: what can grow scrolls inside its own panel or column. A page
	without `fit` scrolls under a header that stays in place.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';

	let { fit = false, children }: { fit?: boolean; children: Snippet } = $props();
</script>

<div class="flex min-h-dvh flex-col {fit ? 'lg:h-dvh' : ''}">
	<AppHeader sticky={!fit} />
	<div class="flex min-h-0 flex-1 flex-col">
		{@render children()}
	</div>
</div>

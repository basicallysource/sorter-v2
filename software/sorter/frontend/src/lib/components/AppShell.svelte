<!--
	The app's frame: the header, and under it the page on the canvas
	(software/sorter-design-system/docs/layout.md). From lg up the screen is
	exactly the window and the page itself never scrolls. By default the area
	under the header is one column that scrolls; with `fit` the page places its
	own panels and columns in that area and scrolls what can grow inside them.
	On a phone it is one column that scrolls, under a header that stays in place.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';

	let { fit = false, children }: { fit?: boolean; children: Snippet } = $props();
</script>

<div class="flex min-h-dvh flex-col lg:h-dvh">
	<AppHeader sticky={!fit} />
	<div class="flex min-h-0 flex-1 flex-col {fit ? '' : 'lg:overflow-y-auto'}">
		{@render children()}
	</div>
</div>

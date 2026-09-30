<!--
	A live example on a site page, on the plane it lives on (a surface unless
	`on` says otherwise), with the code that makes it under it.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		on = 'surface',
		code,
		pad = true,
		children
	}: {
		on?: 'surface' | 'canvas' | 'well';
		code?: string;
		pad?: boolean;
		children: Snippet;
	} = $props();

	const plane = $derived({ surface: 'bg-surface', canvas: 'bg-canvas', well: 'bg-well' }[on]);
</script>

<div class="overflow-hidden rounded-panel bg-surface">
	<div class="{plane} {pad ? 'p-6' : ''} {on === 'canvas' ? 'm-2 rounded-control' : ''}">
		{@render children()}
	</div>
	{#if code}
		<pre
			class="overflow-x-auto border-t border-line bg-surface px-5 py-4 font-mono text-sm leading-relaxed text-ink-muted"><code
				>{code.trim()}</code
			></pre>
	{/if}
</div>

<!--
	The box a condition's value is edited in when the value is made of pieces
	(chips, a list of parts): drawn like a field, so every value in a row of
	conditions has the same outline and a problem draws the same red edge.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		invalid = false,
		class: className = '',
		children
	}: { invalid?: boolean; class?: string; children: Snippet } = $props();
</script>

<div
	class="min-w-0 rounded-control border bg-field transition-colors {invalid
		? 'border-danger outline-2 -outline-offset-1 outline-danger'
		: 'border-line-strong'} {className}"
>
	{@render children()}
</div>

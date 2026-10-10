<!--
	The chute flap open: flat in the chute wall, as an icon for the buttons that lock that
	angle: the small form of ChuteFlapDiagram, drawn like a Lucide icon (24
	units, strokes in the current color) so it sits in a Button. It draws a
	little larger than the size asked for, since a flap at Lucide's 14px
	cannot be read.
-->
<script lang="ts">
	let { size = 24, class: className = '' }: { size?: number; class?: string } = $props();
	const drawn = $derived(Math.round(size * 1.4));
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	width={drawn}
	height={drawn}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-linecap="round"
	stroke-linejoin="round"
	class="-my-1 {className}"
	aria-hidden="true"
>
	<path d="M3 1v22M13 1v3.5M13 16v7M13 4.5l10 5.8M13 16l10 5.8" stroke-width="1.75" opacity="0.6" />
	<path d="M13 16V4.5" stroke-width="3" />
</svg>

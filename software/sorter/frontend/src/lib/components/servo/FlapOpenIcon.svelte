<!--
	The chute flap open: flat in the chute wall, as an icon for the buttons that lock that
	angle: the small form of ChuteFlapDiagram, drawn like a Lucide icon (24
	units, 2-unit strokes in the current color) so it sits in a Button.
-->
<script lang="ts">
	let { size = 24, class: className = '' }: { size?: number; class?: string } = $props();
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	class={className}
	aria-hidden="true"
>
	<path d="M5 2v20M14 2v5M14 17v5M14 7l8 4.5M14 17l8 4.5" opacity="0.55" />
	<path d="M14 17 L14 7" stroke-width="3.25" />
</svg>

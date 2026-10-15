<!--
	docs/icons.md#the-issue-glyphs. The six marks of what can be wrong with the
	photos of a piece: it is not a LEGO piece, several pieces are in the frame,
	none is, pieces are joined, pieces are tangled, or the picture is blurred.
	Lucide has no picture of a LEGO piece, so these are drawn here, like a
	Lucide icon: a 24-unit grid, strokes of 2 in the current color, square caps
	and mitred joins, so they sit with the others. They are made to be read at
	20px (the size of an `IssueToggle`): few shapes, each a unit or more thick.

	<IssueIcon glyph="blurry" size={20} />
-->
<script lang="ts" module>
	export type IssueGlyph =
		'not-lego' | 'multiple-pieces' | 'no-piece' | 'assembly' | 'entangled' | 'blurry';
</script>

<script lang="ts">
	let {
		glyph,
		size = 20,
		class: className = ''
	}: { glyph: IssueGlyph; size?: number; class?: string } = $props();
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="square"
	stroke-linejoin="miter"
	class={className}
	aria-hidden="true"
>
	{#if glyph === 'not-lego'}
		<!-- A brick, struck through. -->
		<path d="M3 13h14v8H3z" opacity=".75" />
		<path d="M5.5 10h3v3h-3z M11.5 10h3v3h-3z" fill="currentColor" stroke="none" opacity=".75" />
		<path d="M4 3l17 17" />
	{:else if glyph === 'multiple-pieces'}
		<!-- Two bricks. -->
		<path d="M2 10h11v6H2z" />
		<path d="M4.5 7h3v3h-3z" fill="currentColor" stroke="none" />
		<path d="M11 18h11v4H11z" />
		<path d="M13.5 15h3v3h-3z" fill="currentColor" stroke="none" />
	{:else if glyph === 'no-piece'}
		<!-- An empty frame. -->
		<path d="M3 8V3h5 M16 3h5v5 M21 16v5h-5 M8 21H3v-5" />
	{:else if glyph === 'assembly'}
		<!-- A brick on a brick. -->
		<path d="M2 15h20v6H2z" />
		<path d="M6 15v-5h12v5" />
		<path d="M8.5 6.5h3V10h-3z M13.5 6.5h3V10h-3z" fill="currentColor" stroke="none" />
	{:else if glyph === 'entangled'}
		<!-- Two links through each other. -->
		<rect x="2" y="7" width="13" height="10" rx="5" />
		<rect x="9" y="7" width="13" height="10" rx="5" />
	{:else if glyph === 'blurry'}
		<!-- A piece, smeared sideways. -->
		<path d="M10 5h11v14H10z" />
		<path d="M2 8h5 M2 12h5 M2 16h5" />
	{/if}
</svg>

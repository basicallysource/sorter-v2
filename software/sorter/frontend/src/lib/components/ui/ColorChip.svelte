<!--
	docs/components.md#profiles. A LEGO color: a small swatch of its RGB with
	a hairline around it, so white and clear still read, then its name. The
	catalog gives RGB as six hex digits with no #; a missing or malformed
	value draws no swatch. It takes its size and ink from the text around it,
	so a muted line gets a muted name.

	<ColorChip name="Dark Bluish Gray" rgb="6C6E68" />
-->
<script module lang="ts">
	// A catalog RGB ("C91A09", or "#C91A09") as a CSS color; null when it is
	// missing or malformed.
	export function swatchColor(rgb: string | null | undefined): string | null {
		const hex = rgb?.trim().replace(/^#/, '') ?? '';
		return /^([0-9a-f]{3}|[0-9a-f]{6})$/i.test(hex) ? `#${hex}` : null;
	}
</script>

<script lang="ts">
	let {
		name = null,
		rgb = null,
		class: className = ''
	}: {
		name?: string | null;
		rgb?: string | null;
		class?: string;
	} = $props();

	const color = $derived(swatchColor(rgb));
</script>

<span class="inline-flex min-w-0 items-center gap-1.5 {className}">
	{#if color}
		<span
			aria-hidden="true"
			class="size-4 shrink-0 rounded-check border border-line-strong"
			style:background-color={color}
		></span>
	{/if}
	{#if name}<span class="truncate" title={name}>{name}</span>{/if}
</span>

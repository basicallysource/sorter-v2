<!--
	docs/components.md#progress. How far along something is, when that is
	known. A track and a fill; no border, no stripes, no animation but the
	width. When how far is not known, it is the Spinner.
-->
<script lang="ts">
	let {
		value,
		max = 100,
		label,
		tone = 'primary'
	}: {
		value: number;
		max?: number;
		// The accessible name ("Copying samples").
		label: string;
		tone?: 'primary' | 'success' | 'warning' | 'danger';
	} = $props();

	const share = $derived(Math.max(0, Math.min(1, value / max)));
	const fill = $derived(
		{ primary: 'bg-primary', success: 'bg-success', warning: 'bg-warning', danger: 'bg-danger' }[
			tone
		]
	);
</script>

<div
	role="progressbar"
	aria-label={label}
	aria-valuemin={0}
	aria-valuemax={max}
	aria-valuenow={value}
	class="h-1.5 w-full overflow-hidden rounded-badge bg-track"
>
	<div class="h-full transition-[width] duration-300 {fill}" style="width: {share * 100}%"></div>
</div>

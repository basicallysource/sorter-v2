<!--
	docs/components.md#stat. One number and its name. Stats in a row sit in
	a `grid divide-x divide-line` inside a flush Panel, so the lines fall
	between them only.
-->
<script lang="ts">
	let {
		label,
		value,
		unit,
		hint,
		tone
	}: {
		label: string;
		value: string | number;
		unit?: string;
		hint?: string;
		tone?: 'success' | 'warning' | 'danger';
	} = $props();

	const ink = $derived(
		tone
			? { success: 'text-success-ink', warning: 'text-warning-ink', danger: 'text-danger-ink' }[
					tone
				]
			: 'text-ink'
	);
</script>

<div class="min-w-0 px-5 py-4">
	<div class="label truncate">{label}</div>
	<div class="mt-1.5 flex items-baseline gap-1">
		<span class="num text-2xl leading-none font-medium {ink}">{value}</span>
		{#if unit}<span class="text-sm text-ink-muted">{unit}</span>{/if}
	</div>
	{#if hint}<div class="mt-1.5 truncate text-sm text-ink-muted">{hint}</div>{/if}
</div>

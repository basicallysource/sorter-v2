<!--
	docs/components.md#key-value. Facts about one thing: a machine's version,
	address, uptime. The name on the left in muted ink, the value on the
	right, one line between pairs. `mono` for a value someone might copy (an
	address, a hash, an id).
-->
<script lang="ts">
	type Pair = { label: string; value: string | number; mono?: boolean };

	let { items }: { items: Pair[] } = $props();
</script>

<dl class="divide-y divide-line">
	{#each items as item (item.label)}
		<div class="flex items-baseline justify-between gap-6 py-2.5">
			<dt class="shrink-0 text-sm text-ink-muted">{item.label}</dt>
			<dd class="min-w-0 truncate text-right text-sm text-ink {item.mono ? 'font-mono' : ''}">
				{item.value}
			</dd>
		</div>
	{/each}
</dl>

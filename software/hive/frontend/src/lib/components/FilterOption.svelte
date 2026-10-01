<!--
	One choice in a FilterGroup, as on the samples and piece samples pages: the
	chosen one takes the primary's tint, like a side nav item.
-->
<script lang="ts">
	let {
		label,
		on,
		onclick,
		count = null,
		title
	}: { label: string; on: boolean; onclick: () => void; count?: number | null; title?: string } = $props();
</script>

<li>
	<button
		type="button"
		{onclick}
		{title}
		aria-pressed={on}
		class="flex h-(--size-nav-item) w-full items-center gap-2 rounded-item px-2.5 text-left text-sm {on
			? 'bg-primary-soft font-medium text-primary-ink'
			: 'text-ink hover:bg-hover'}"
	>
		<span class="min-w-0 flex-1 truncate">{label}</span>
		{#if count != null}<span class="num text-xs text-ink-faint">{count.toLocaleString()}</span>{/if}
	</button>
</li>

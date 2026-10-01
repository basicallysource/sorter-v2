<!--
	docs/components.md#disclosure. A section that opens and closes, for the
	settings most people never touch ("Driver settings"). The browser's own
	details element, so it works with the keyboard and find-in-page. Put it
	in a divided list like a SettingRow; its content indents under the title.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	let {
		title,
		help,
		open = $bindable(false),
		children
	}: { title: string; help?: string; open?: boolean; children: Snippet } = $props();
</script>

<details bind:open class="group">
	<summary
		class="flex list-none items-center gap-2 px-(--pad-panel) py-(--pad-row) hover:bg-hover [&::-webkit-details-marker]:hidden"
	>
		<ChevronRight
			size={16}
			class="shrink-0 text-ink-muted transition-transform group-open:rotate-90"
		/>
		<span class="shrink-0 text-sm font-medium text-ink">{title}</span>
		{#if help}<span class="min-w-0 truncate text-sm text-ink-muted">{help}</span>{/if}
	</summary>
	<div class="pb-2">
		{@render children()}
	</div>
</details>

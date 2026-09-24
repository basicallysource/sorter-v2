<script lang="ts">
	// The Sorter app's header: the blue square and the wordmark, then the
	// machine's name.
	let { name }: { name: string | null } = $props();
</script>

<header class="border-b border-border bg-surface">
	<div class="mx-auto flex max-w-md items-center justify-between gap-3 px-4 py-3">
		<span class="flex items-center gap-2.5 font-mono text-lg font-bold tracking-tight text-text uppercase">
			<span class="h-4 w-4 shrink-0 bg-primary" aria-hidden="true"></span>
			Sorter
		</span>
		{#if name}
			<span class="min-w-0 truncate border border-border px-2.5 py-1 text-sm font-medium text-text-muted">
				{name}
			</span>
		{/if}
	</div>
</header>

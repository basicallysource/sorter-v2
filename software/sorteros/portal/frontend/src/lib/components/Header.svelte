<script lang="ts">
	// The Sorter UI's top bar: the primary square and the name, then the
	// machine's own name.
	let { name }: { name: string | null } = $props();
</script>

<header class="border-b border-line bg-surface">
	<div class="mx-auto flex h-(--size-topbar) max-w-md items-center justify-between gap-3 px-4">
		<span class="flex items-center gap-2.5 text-base font-semibold tracking-tight text-ink">
			<span class="size-4 shrink-0 bg-primary" aria-hidden="true"></span>
			Sorter
		</span>
		{#if name}
			<span class="min-w-0 truncate text-sm text-ink-muted">{name}</span>
		{/if}
	</div>
</header>

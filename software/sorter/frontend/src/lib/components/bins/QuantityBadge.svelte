<script lang="ts">
	let { count, size = 'lg' }: { count: number; size?: 'sm' | 'lg' } = $props();
</script>

{#if size === 'sm'}
	<div
		class="absolute top-1 right-1 z-10 flex h-5 min-w-5 items-center justify-center bg-primary px-1 text-xs font-semibold tabular-nums text-primary-contrast shadow-sm"
	>
		×{count}
	</div>
{:else}
	<div
		class="absolute top-3 right-3 flex h-10 min-w-10 items-center justify-center bg-primary px-3 text-lg font-semibold tabular-nums text-primary-contrast shadow-sm"
	>
		{count}
	</div>
{/if}

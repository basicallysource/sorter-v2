<script lang="ts">
	// Placeholder card shown while a target's Hive profiles are still loading.
	// Mirrors ProfileCard's header, rules and footer so the grid doesn't jump
	// when the real cards replace it.
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
</script>

<div class="flex h-full flex-col gap-3 rounded-panel bg-surface p-(--pad-panel)" aria-busy="true">
	<div class="flex items-center justify-between gap-3">
		<Skeleton class="h-5 w-40" />
		<Skeleton class="h-(--size-control-sm) w-24" />
	</div>
	<div class="grid grid-cols-1 gap-x-4 gap-y-2 md:grid-cols-2">
		{#each Array(4) as _}
			<div class="flex items-center gap-2">
				<Skeleton class="size-4 shrink-0" />
				<Skeleton class="h-4 w-full" />
			</div>
		{/each}
	</div>
	<Skeleton class="mt-auto h-4 w-3/4" />
</div>

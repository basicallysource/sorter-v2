<script lang="ts">
	// Placeholder card shown while a target's Hive profiles are still loading.
	// Mirrors ProfileCard's header + rules + footer layout so the grid doesn't
	// jump when real cards replace it.
	import Skeleton from '$lib/components/primitives/Skeleton.svelte';
</script>

<div class="setup-card-shell flex h-full flex-col overflow-hidden border border-border">
	<div class="setup-card-header px-3 py-2 text-sm">
		<div class="flex items-center justify-between gap-3">
			<Skeleton class="h-5 w-40" />
			<Skeleton class="h-9 w-[10.5rem]" />
		</div>
	</div>
	<div class="setup-card-body border-t border-border px-4 py-3">
		<div class="grid gap-x-4 gap-y-1.5 md:grid-cols-2">
			{#each Array(4) as _}
				<div class="flex items-center gap-2">
					<Skeleton class="h-3.5 w-3.5 shrink-0" />
					<Skeleton class="h-3.5 w-full" />
				</div>
			{/each}
		</div>
	</div>
	<div class="setup-card-body border-t border-border px-4 py-3">
		<Skeleton class="h-3.5 w-3/4" />
	</div>
</div>

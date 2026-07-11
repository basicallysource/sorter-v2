<script lang="ts">
	import VersionsSection from '$lib/components/settings/VersionsSection.svelte';
</script>

<svelte:head><title>Sorter - Versions</title></svelte:head>

<div class="flex flex-col gap-4 lg:max-w-4xl">
	<header>
		<h1 class="text-xl font-semibold text-text">Versions</h1>
		<p class="mt-1 text-sm text-text-muted">
			See which software version this machine is running and update it with one click.
		</p>
	</header>

	<VersionsSection />
</div>

<script lang="ts">
	import HiveModelsSection from '$lib/components/settings/HiveModelsSection.svelte';
	import HiveRuntimesSection from '$lib/components/settings/HiveRuntimesSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
</script>

<svelte:head><title>Sorter - Detection Models</title></svelte:head>

<div class="flex flex-col gap-8">
	<!-- Page intro: kept slim so the hero inside HiveModelsSection takes
	     visual ownership instead of competing with a redundant SectionCard. -->
	<header>
		<h1 class="text-lg font-semibold text-text">Detection Models</h1>
		<p class="mt-1 max-w-3xl text-sm text-text-muted">
			Manage which neural-network model the sorter uses for live detection. The
			bundled YOLO model ships with the repo and is the default fallback if
			nothing else is installed.
		</p>
	</header>

	<HiveModelsSection />

	<SectionCard
		title="Model Compatibility & Benchmark"
		description="For each shipping model format, which inference backends this machine can run and how fast they're expected to be on the selected model."
	>
		<HiveRuntimesSection />
	</SectionCard>
</div>

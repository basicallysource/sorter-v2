<script lang="ts">
	import HiveModelsSection from '$lib/components/settings/HiveModelsSection.svelte';
</script>

<div class="flex flex-col gap-8">
	<!-- Page intro: kept slim so the model list takes visual ownership. -->
	<header>
		<h1 class="text-lg font-semibold text-text">Detection Models</h1>
		<p class="mt-1 max-w-3xl text-sm text-text-muted">
			Manage which neural-network model the sorter uses for live detection. Downloaded models can be
			activated for all channels in one click or benchmarked per backend. The bundled YOLO model
			ships with the repo and is the default fallback if nothing else is installed.
		</p>
	</header>

	<HiveModelsSection />
</div>

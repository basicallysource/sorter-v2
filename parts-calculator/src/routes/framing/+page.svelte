<script lang="ts">
	import Seo from '$lib/components/Seo.svelte';
	import ExtrusionScene from '$lib/components/ExtrusionScene.svelte';
	import LayerControl from '$lib/components/LayerControl.svelte';
	import CutPlan from '$lib/components/CutPlan.svelte';
	import Figure from '$lib/components/Figure.svelte';
</script>

<Seo
	title="Aluminium framing"
	description="Aluminium extrusion cut list for the Sorter V2 frame — every T-slot length and quantity, with an optimised cutting plan."
/>

<div class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
	<header class="mb-5">
		<h1 class="text-2xl font-bold text-text">Aluminium framing</h1>
		<p class="mt-1 text-sm text-text-muted">
			2020 T-slot extrusion, cut from 1 m bars. Below is the piece family at a glance, then a cut
			plan that packs the pieces into bars with the least waste.
		</p>
	</header>

	<section class="mb-6">
		<LayerControl />
	</section>

	<section class="mb-8">
		<ExtrusionScene>
			{#snippet aside()}
				<Figure
					src="/extrusion-explainer.png"
					alt="Extrusion assembly explainer"
					title="Extrusion assembly explainer"
					caption="The foot extensions (D) aren't in the CAD yet. On a build they replace the C supports on the bottom two layers, one D spanning both."
					imgClass="max-h-[32vh]"
				/>
			{/snippet}
		</ExtrusionScene>
	</section>

	<section>
		<h2 class="mb-3 text-base font-semibold text-text">Cut plan</h2>
		<CutPlan />
	</section>
</div>

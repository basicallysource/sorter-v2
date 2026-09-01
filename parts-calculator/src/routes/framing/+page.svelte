<script lang="ts">
	import Seo from '$lib/components/Seo.svelte';
	import ExtrusionScene from '$lib/components/ExtrusionScene.svelte';
	import LayerControl from '$lib/components/LayerControl.svelte';
	import CutPlan from '$lib/components/CutPlan.svelte';
	import Figure from '$lib/components/Figure.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import { FRAMING_PIECES, CLEARANCE_MM } from '$lib/framing';

	// lengths quoted in the C/D note below, read off the pieces themselves
	const lenC = FRAMING_PIECES.find((p) => p.letter === 'C')?.len ?? 0;
	const lenD = FRAMING_PIECES.find((p) => p.letter === 'D')?.len ?? 0;
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
					src="https://assets.basically.website/sorter-parts/extrusion-assembly-explainer-full-7991b2c2abd8.png"
					alt="Extrusion assembly explainer"
					title="Extrusion assembly explainer"
					caption="The foot extensions (D) aren't in the CAD yet. On a build they replace the C supports on the bottom two layers, one D spanning both."
					imgClass="max-h-[32vh]"
				/>
			{/snippet}
		</ExtrusionScene>
	</section>

	<section class="mb-8">
		<Callout variant="info" title="Notes">
			<ul class="list-disc space-y-2 pl-4 leading-relaxed">
				<li class="flow-root">
					<div class="float-right ml-3 mb-1 w-40 sm:w-48">
						<Figure
							src="https://assets.basically.website/sorter-parts/img-0036-full-76e2483ec1e7.jpg"
							alt="Two 2020 extrusion profiles held end-on side by side — the right one has angular T-slot corners, the left one has rounded corners"
							caption="Right: angular corners, seats tight. Left: rounded corners, fits loose."
							credit="sytem"
							imgClass="max-h-40"
						/>
					</div>
					<b class="text-text">Not all 2020 extrusion is the same stock.</b> Builders have found that
					secondhand 20×20 mm profile varies: one with more angular, square corners on the T-slot seats
					tightly against the crossbeam brackets, while a profile with more rounded corners can fit
					loosely and add friction. Check the corner profile before buying, especially secondhand.
				</li>
				<li>
					<b class="text-text">D stands in for C at the bottom.</b> Every layer above the bottom two
					gets 6 layer supports (<b class="text-text">C</b>, {lenC} mm). The bottom two share 6 foot
					extensions (<b class="text-text">D</b>, {lenD} mm), one spanning both, in place of a C on
					each. So a 1 or 2 layer build has no C in the list at all, and that is not a missing piece.
				</li>
				<li>
					Pieces that share a cut length stack together at the saw — mark and cut the top bar, the rest
					follow: <b class="text-text">A &amp; G</b> = 320 mm, <b class="text-text">B &amp; H</b> = 158 mm.
				</li>
				<li>
					Where the cut length is under the CAD length, the piece is trimmed {CLEARANCE_MM} mm for
					tolerance (see the <b class="text-text">Cut length</b> note above).
				</li>
			</ul>
		</Callout>
	</section>

	<section>
		<h2 class="mb-3 text-base font-semibold text-text">Cut plan</h2>
		<CutPlan />
	</section>
</div>

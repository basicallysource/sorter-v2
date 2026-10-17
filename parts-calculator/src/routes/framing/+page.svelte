<script lang="ts">
	import Seo from '$lib/components/Seo.svelte';
	import ExtrusionScene from '$lib/components/ExtrusionScene.svelte';
	import BuildOptions from '$lib/components/BuildOptions.svelte';
	import CutPlan from '$lib/components/CutPlan.svelte';
	import Figure from '$lib/components/Figure.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import { FRAMING_PIECES, CLEARANCE_MM } from '$lib/framing';

	// lengths quoted in the C/D note below, read off the pieces themselves
	const lenC = FRAMING_PIECES.find((p) => p.letter === 'C')?.len ?? 0;
	const lenD = FRAMING_PIECES.find((p) => p.letter === 'D')?.len ?? 0;
	const lenJ = FRAMING_PIECES.find((p) => p.letter === 'J')?.len ?? 0;
</script>

<Seo
	title="Aluminium framing"
	description="Aluminium extrusion cut list for the Sorter V2 frame and feeder — every T-slot length and quantity, with an optimised cutting plan."
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
		<BuildOptions />
	</section>

	<section class="mb-8">
		<ExtrusionScene>
			{#snippet aside()}
				<Figure
					src="https://assets.basically.website/sorter-parts/extrusion-assembly-explainer-full-full-68c62d8a10b3.png"
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
					each. So a 1 layer build has no C in the list at all, and that is not a missing piece.
				</li>
				<li>
					<b class="text-text">The top layer needs a C too.</b> The interface frame, the hex frame the
					electronics bolt onto, is its own ring above the top bin layer, so there is a run of
					<b class="text-text">C</b> between the two. Piece <b class="text-text">F</b> only spans from
					that frame up into the Interface brackets. That is why C comes out at 6 × (layers − 1)
					rather than one set per layer.
				</li>
				<li>
					<b class="text-text">J is a feeder piece, not a frame one.</b> C-channel 1 stands on
					three legs of the same 2020 extrusion (<b class="text-text">J</b>, {lenJ} mm) standing in
					its layout guide. C-channels 2 and 3 use printed legs instead (148 mm and 68 mm) and
					C-channel 4 has none, so it is 3 per machine whatever the layer count. It is listed here
					because it is cut from the same bars as the frame.
				</li>
				<li>
					<b class="text-text">A &amp; G and B &amp; H are one cut each.</b> A and G are the same
					320 mm piece doing two jobs, on a layer's hex frame and on the interface frame; B and H
					are the same 158 mm spoke. They are one row here because they are one part in the
					catalog, and they stack together at the saw: mark and cut the top bar, the rest follow.
				</li>
				<li>
					Where the cut length is under the CAD length, the piece is trimmed {CLEARANCE_MM} mm for
					tolerance (see the <b class="text-text">Cut length</b> note above).
				</li>
				<li>
					<b class="text-text">Every quantity here comes from the parts catalog.</b> Each piece is
					a part in <code class="text-xs">catalog/parts.json</code>, placed in the machine
					assembly tree, so this list, the Hardware tab and the docs site are all counting the same
					thing. Nothing about the framing is written down twice.
				</li>
			</ul>
		</Callout>
	</section>

	<section id="where-to-get-it-cut" class="mb-8">
		<h2 class="mb-3 text-base font-semibold text-text">Where to get it cut</h2>
		<p class="mb-3 leading-relaxed">
			Ordering every piece cut to length saves you the saw. The fee per cut differs a lot between
			suppliers, so ask for the price per cut and multiply it by the piece count before you order.
		</p>
		<ul class="list-disc space-y-2 pl-5 leading-relaxed">
			<li>
				<b class="text-text">United States:</b>
				<a class="text-primary hover:text-primary-hover" target="_blank" rel="noopener" href="https://www.tnutz.com/">TNUTZ</a> cuts each piece to the length you enter. Their
				cuts fit the printed parts.
				<a class="text-primary hover:text-primary-hover" target="_blank" rel="noopener" href="https://www.zyltech.com/">Zyltech</a> also cuts, but charges more per cut and
				throws away the leftover bar unless you ask to keep it.
			</li>
			<li>
				<b class="text-text">Germany, Austria, Belgium, France, Luxembourg, Netherlands:</b>
				<a class="text-primary hover:text-primary-hover" target="_blank" rel="noopener" href="https://easy-systemprofile.de/">easy-systemprofile.de</a> cuts to any length. They
				can also cut an M6 thread into the end of a profile, which the casters can screw into.
			</li>
			<li>
				<b class="text-text">United Kingdom:</b>
				<a class="text-primary hover:text-primary-hover" target="_blank" rel="noopener" href="https://ooznest.co.uk/product/20x20mm-t-v-slot-aluminium-extrusion-profile-silver-cut-to-size/">Ooznest</a>
				cuts to size. Ask them to confirm the slot is 6 mm wide before you order.
			</li>
			<li>
				<b class="text-text">Several regions:</b>
				<a class="text-primary hover:text-primary-hover" target="_blank" rel="noopener" href="https://www.motedis.com/">Motedis</a> cuts to length and cuts M6 threads. Pick your
				country in the shop: it covers most of Europe, the UK, Mexico and the United States.
			</li>
		</ul>
		<p class="mt-3 leading-relaxed">
			Order every piece from one supplier in one order. Ask for 20×20 T-slot extrusion with a 6 mm slot.
		</p>
	</section>

	<section>
		<h2 class="mb-3 text-base font-semibold text-text">Cut plan</h2>
		<CutPlan />
	</section>
</div>

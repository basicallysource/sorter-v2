<script lang="ts">
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import ColorChoice from '$lib/components/ColorChoice.svelte';
	import { swatchColor } from '$lib/components/ColorChip.svelte';
	import PieceReview from '$lib/components/PieceReview.svelte';
	import { palette, ranked, rankedByColor } from '$lib/site/review-samples';

	const ISSUES = [
		{ code: 'not_lego', label: 'Not LEGO' },
		{ code: 'multiple_pieces', label: 'Multiple pieces in frame' },
		{ code: 'no_piece', label: 'No piece in frame' },
		{ code: 'assembly', label: 'Assembly' },
		{ code: 'pieces_entangled', label: 'Pieces entangled' },
		{ code: 'blurry', label: 'Blurry' }
	];
	const orange = palette.find((c) => c.id === 4)!;

	let partVerdict = $state<boolean | null>(null);
	let correctedId = $state<number | null>(null);
	let issues = $state<string[]>([]);
	let likely = $state<typeof ranked | null>(null);

	let labeled = $state<number | null>(4);
	let alone = $state<number | null>(null);

	// What Hive puts beside the grid: the colors the part sells in, most first.
	const sold = ranked
		.filter((c) => (c.qty ?? 0) > 0)
		.sort((a, b) => (b.qty ?? 0) - (a.qty ?? 0))
		.slice(0, 6);
	const byId = new Map(palette.map((c) => [c.id, c]));

	function toggleIssue(code: string) {
		issues = issues.includes(code) ? issues.filter((c) => c !== code) : [...issues, code];
	}

	// The ranking arrives a moment after the colors open, as it does from a machine.
	function picking(open: boolean) {
		if (!open || likely) return;
		setTimeout(() => (likely = ranked), 600);
	}
</script>

<svelte:head><title>Color review · Sorter design system</title></svelte:head>

<PageHeader
	title="Color review"
	lead="How a person checks a classified piece: the part, the color, and what is wrong with the photos. When the color is wrong, the colors it most likely is come first, ranked by how near they are to the prediction and how often the part is sold in them."
	doc="components"
/>

<SiteSection
	title="The review"
	lead="Three questions, each a row: the name on the left, the answer on the right, lines between them. No opens the likely colors right under the color; a pick is staged and saved with Confirm, and Cancel closes it. The same block is in the sorter's correction dialog and on its records."
>
	<Specimen
		code={`<PieceReview {palette} {likely} predicted={orange} predictedMark="Predicted 82%"
	{partVerdict} {correctedId} issues={ISSUES} activeIssues={flags}
	onpart={savePart} oncolor={saveColor} onissue={toggleIssue} onpicking={loadLikely} />`}
	>
		<div class="max-w-3xl">
			<PieceReview
				{palette}
				{likely}
				predicted={orange}
				predictedMark="Predicted 82%"
				{partVerdict}
				{correctedId}
				issues={ISSUES}
				activeIssues={issues}
				onpart={(v) => (partVerdict = v)}
				oncolor={(id) => {
					correctedId = id;
					return true;
				}}
				onissue={toggleIssue}
				onpicking={picking}
			/>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Likely colors"
	lead="The best twelve as compact swatches with their names, then a search of every color: its matches list as they are typed and Enter picks the first, All colors lists the whole palette, and otherwise nothing is listed. Under each name, its share of the part's pieces for sale (how near it is shows in the swatch); the tooltip has every number. A predicted color and the chosen one are always in the grid. Hive's labeling page uses this on its own, as its True color, with the part's sales on BrickLink beside the grid."
>
	<Specimen
		code={`<ColorChoice {palette} likely={ranked} value={chosen} marks={{ 4: 'The guess' }} onpick={pick}>
	{#snippet aside()}...the part's sales on BrickLink...{/snippet}
</ColorChoice>`}
	>
		<div class="max-w-3xl">
			<ColorChoice
				{palette}
				likely={ranked}
				value={labeled}
				count={8}
				marks={{ 4: 'The guess' }}
				onpick={(id) => (labeled = id)}
			>
				{#snippet aside()}
					<section class="flex flex-col gap-1.5">
						<h3 class="label">Sold on BrickLink</h3>
						<ul class="flex flex-col">
							{#each sold as c (c.color_id)}
								<li class="flex items-center gap-2 px-1.5 py-0.5 text-sm text-ink">
									<span
										aria-hidden="true"
										class="size-4 shrink-0 rounded-check border border-line-strong"
										style:background-color={swatchColor(byId.get(c.color_id)?.rgb)}
									></span>
									<span class="min-w-0 flex-1 truncate">{byId.get(c.color_id)?.name}</span>
									<span class="num text-xs text-ink-muted">{(c.qty ?? 0).toLocaleString()}</span>
								</li>
							{/each}
						</ul>
					</section>
				{/snippet}
			</ColorChoice>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Without sale numbers"
	lead="When the machine cannot reach Hive, it ranks by color alone and says so in a line under the heading. While a ranking loads, the grid holds its place."
>
	<Specimen
		code={`<ColorChoice {palette} likely={byColor} note="By color alone: the machine cannot reach Hive." ... />
<ColorChoice {palette} likely={null} ... />`}
	>
		<div class="grid max-w-5xl gap-10 lg:grid-cols-2">
			<ColorChoice
				{palette}
				likely={rankedByColor}
				value={alone}
				marks={{ 4: 'Predicted 82%' }}
				note="By color alone: the machine cannot reach Hive."
				onpick={(id) => (alone = id)}
			/>
			<ColorChoice {palette} likely={null} marks={{ 4: 'Predicted 82%' }} onpick={() => {}} />
		</div>
	</Specimen>
</SiteSection>

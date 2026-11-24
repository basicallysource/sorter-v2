<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import Pipette from '@lucide/svelte/icons/pipette';
	import Button from '$lib/components/ui/Button.svelte';
	import type { IssueGlyph } from '$lib/components/ui/IssueIcon.svelte';
	import IssueToggle from '$lib/components/ui/IssueToggle.svelte';
	import PieceReview from '$lib/components/ui/PieceReview.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import type { PieceView } from './model';

	// The review of a piece as the layouts on /layouts show it. It answers the
	// pointer and saves nothing: the page is for looking. `line` is the three
	// questions on one line, for a layout whose row is one line tall.
	let {
		piece,
		layout
	}: {
		piece: PieceView;
		layout: 'full' | 'compact' | 'line';
	} = $props();

	const ISSUES: { code: string; label: string; glyph: IssueGlyph }[] = [
		{ code: 'not_lego', label: 'Not LEGO', glyph: 'not-lego' },
		{ code: 'multiple_pieces', label: 'Multiple pieces in frame', glyph: 'multiple-pieces' },
		{ code: 'no_piece', label: 'No piece in frame', glyph: 'no-piece' },
		{ code: 'assembly', label: 'Assembly', glyph: 'assembly' },
		{ code: 'pieces_entangled', label: 'Pieces entangled', glyph: 'entangled' },
		{ code: 'blurry', label: 'Blurry', glyph: 'blurry' }
	];

	let verdict = $state<boolean | null>(null);
	let colorRight = $state(false);
	let flagged = $state<string[]>([]);

	const predicted = $derived(
		piece.color ? { id: piece.color.id, name: piece.color.name, rgb: piece.color.hex } : null
	);

	function toggle(code: string) {
		flagged = flagged.includes(code) ? flagged.filter((c) => c !== code) : [...flagged, code];
	}
</script>

{#if layout === 'line'}
	<div class="flex shrink-0 items-center gap-x-4">
		<span class="flex items-center gap-2">
			<span class="text-sm text-ink-muted">Part</span>
			<SegmentedControl
				label="Is the predicted part right?"
				size="sm"
				value={verdict === true ? 'yes' : verdict === false ? 'no' : ''}
				options={[
					{ value: 'yes', label: 'Yes' },
					{ value: 'no', label: 'No' }
				]}
				onchange={(v) => (verdict = v === 'yes')}
			/>
		</span>
		<span class="flex items-center gap-2">
			<span class="text-sm text-ink-muted">Color</span>
			<Button
				size="sm"
				variant={colorRight ? 'primary' : 'secondary'}
				icon={Check}
				onclick={() => (colorRight = !colorRight)}
			>
				Yes
			</Button>
			<Button size="sm" icon={Pipette} label="No, pick the color" />
		</span>
		<span role="group" aria-label="Report an issue" class="flex items-center gap-1">
			{#each ISSUES as issue (issue.code)}
				<IssueToggle
					glyph={issue.glyph}
					label={issue.label}
					on={flagged.includes(issue.code)}
					onchange={() => toggle(issue.code)}
				/>
			{/each}
		</span>
	</div>
{:else}
	<PieceReview
		{layout}
		palette={[]}
		{predicted}
		predictedMark={piece.colorPct != null ? `Predicted ${piece.colorPct}%` : 'Predicted'}
		correctedId={colorRight && predicted ? predicted.id : null}
		partVerdict={verdict}
		issues={ISSUES}
		activeIssues={flagged}
		onpart={(correct) => (verdict = correct)}
		oncolor={() => {
			colorRight = true;
			return true;
		}}
		onissue={toggle}
	/>
{/if}

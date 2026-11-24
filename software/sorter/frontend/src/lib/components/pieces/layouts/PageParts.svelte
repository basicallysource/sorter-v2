<script lang="ts" module>
	import type { PieceView } from './model';

	export type Stat = { label: string; value: string; note?: string | null; mono?: boolean };

	// What the machine decided, as facts: a name over a value, and beside the
	// value who decided it or how sure it was.
	export function statsOf(piece: PieceView): Stat[] {
		const stats: Stat[] = [
			{
				label: 'Part',
				value: piece.partPct != null ? `${piece.partPct}% sure` : '—',
				note: piece.partBy
			},
			{
				label: 'Color',
				value: piece.color
					? `${piece.color.name}${piece.colorPct != null ? `, ${piece.colorPct}%` : ''}`
					: '—',
				note: piece.colorBy
			},
			{ label: 'Bin', value: piece.bin ?? '—', mono: true }
		];
		if (piece.value) stats.push({ label: 'Value', value: piece.value });
		if (piece.whenExact) stats.push({ label: 'Seen', value: piece.whenExact });
		return stats;
	}
</script>

<script lang="ts">
	import Disclosure from '$lib/components/ui/Disclosure.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';

	// The fold-outs at the foot of a piece's page. On /layouts they are only
	// named: every layout keeps them as they are.
	const FOLDS = [
		{ title: 'Classification requests', help: 'What was sent, and what came back' },
		{ title: 'Pricing', help: 'The moving average, by color' },
		{ title: 'Lifecycle timeline', help: 'Each step, with its time' },
		{ title: 'Record', help: 'The run and when it was recorded' }
	];
</script>

<Panel flush>
	<div class="divide-y divide-line">
		{#each FOLDS as fold (fold.title)}
			<Disclosure title={fold.title} help={fold.help}>
				<p class="px-(--pad-panel) pb-3 text-sm text-ink-muted">
					As on the page today. The layouts here leave the fold-outs alone.
				</p>
			</Disclosure>
		{/each}
	</div>
</Panel>

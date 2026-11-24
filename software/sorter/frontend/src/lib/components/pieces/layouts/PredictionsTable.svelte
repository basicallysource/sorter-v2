<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { findLegoColor, type PiecePrediction, type PredictionAnswer } from '$lib/pieces';
	import Slot from './Slot.svelte';
	import type { PieceView } from './model';

	// Every prediction made for a piece as a table whose columns have widths of
	// their own: who asked, the parts it named, the colors it named, and the
	// pictures it saw. A score sits beside what it scores, never at the far
	// side of an empty column.
	let { piece }: { piece: PieceView } = $props();

	const SHOWN = 3;
	const PROVIDERS: Record<string, string> = {
		brickognize: 'Brickognize',
		hive_basically: 'basically color model'
	};
	const LIVE: Record<string, string> = {
		combined: 'Combined (fused set)',
		single_burst: 'Single burst frame'
	};

	function requestLabel(p: PiecePrediction): string {
		if (p.source === 'live' && LIVE[p.request]) return LIVE[p.request];
		return p.model_name ?? p.request;
	}

	function answers(p: PiecePrediction, kind: string): PredictionAnswer[] {
		return p.answers.filter((a) => a.kind === kind).slice(0, SHOWN);
	}

	function percent(score: number | null): string {
		return score == null || !Number.isFinite(score) ? '' : `${Math.round(score * 100)}%`;
	}

	const cols = '@4xl:grid-cols-[13rem_minmax(0,21rem)_minmax(0,15rem)_minmax(0,1fr)]';
</script>

<Panel
	title="Predictions"
	description="{piece.predictions.length} request{piece.predictions.length === 1
		? ''
		: 's'} made for this piece."
	flush
>
	<div class="@container">
		<div
			class="hidden gap-x-6 border-b border-line px-(--pad-panel) pb-1.5 text-xs text-ink-muted @4xl:grid {cols}"
		>
			<span>Request</span>
			<span>Part</span>
			<span>Color</span>
			<span>Saw</span>
		</div>
		<ul class="divide-y divide-line">
			{#each piece.predictions as p (p.source + p.request)}
				<li class="grid items-start gap-x-6 gap-y-2 px-(--pad-panel) py-2.5 {cols}">
					<div class="flex min-w-0 flex-col text-sm">
						<span class="truncate font-medium text-ink">{requestLabel(p)}</span>
						<span class="truncate text-xs text-ink-muted">
							{PROVIDERS[p.provider] ?? p.provider}{p.source === 'live' ? ', while sorting' : ''}
						</span>
					</div>
					{#each ['part', 'color'] as kind (kind)}
						<ol class="flex min-w-0 flex-col gap-0.5 text-sm">
							{#each answers(p, kind) as a (a.rank)}
								<li class="flex min-w-0 items-center gap-2">
									<span class="num w-9 shrink-0 text-right text-ink-muted">{percent(a.score)}</span>
									{#if kind === 'color'}
										<ColorChip
											name={a.value_name ?? a.value_id}
											rgb={findLegoColor(a.value_id, a.value_name)?.hex ?? null}
											class="min-w-0 text-ink"
										/>
									{:else}
										<span class="shrink-0 font-mono text-ink">{a.value_id}</span>
										{#if a.value_name}
											<span class="truncate text-ink-muted">{a.value_name}</span>
										{/if}
									{/if}
									{#if a.applied}<Badge tone="info">Applied</Badge>{/if}
								</li>
							{:else}
								<li class="text-ink-faint">—</li>
							{/each}
						</ol>
					{/each}
					<div class="flex min-w-0 flex-wrap gap-1.5">
						{#each p.images ?? [] as image (image.set + image.seq)}
							{@const shot = piece.saw(image)}
							{#if shot}<Slot {shot} size={2} mark={false} />{/if}
						{/each}
					</div>
				</li>
			{/each}
		</ul>
	</div>
</Panel>

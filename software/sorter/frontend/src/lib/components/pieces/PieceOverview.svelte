<script lang="ts">
	import PieceCorrection from '$lib/components/PieceCorrection.svelte';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import type { PieceSummary } from '$lib/pieces';
	import type { Fact } from './types';

	// The top of the right column of a piece's page: Brickognize's picture of
	// the part, its name, what the machine decided as facts (a name over a
	// value, and under the value who decided it), and the review under them.
	// The piece's own pictures are beside it, in the left column
	// (PiecePictures); everything that explains how it got there is below.
	let {
		name,
		partId,
		reference,
		facts,
		summary,
		endpointBase,
		onReviewed,
		onZoom
	}: {
		name: string;
		partId: string | null;
		reference: string | null;
		facts: Fact[];
		// The record the review answers about; null when it cannot be reviewed.
		summary: PieceSummary | null;
		endpointBase: string;
		onReviewed: (summary: PieceSummary) => void;
		onZoom: (src: string, label: string) => void;
	} = $props();
</script>

<Panel flush>
	<div class="@container">
		<div class="flex items-start gap-5 px-(--pad-panel) py-4">
			{#if reference}
				<div class="flex shrink-0 flex-col items-center gap-0.5">
					<ImageZoom src={reference} label="Brickognize's picture of this part">
						<button
							type="button"
							aria-label="Enlarge Brickognize's picture of this part"
							class="block rounded-item p-1 transition-colors hover:bg-hover"
							onclick={() => onZoom(reference, `Brickognize: ${name}`)}
						>
							<PartImage src={reference} class="size-28" />
						</button>
					</ImageZoom>
					<span class="text-xs text-ink-muted">Brickognize</span>
				</div>
			{/if}
			<div class="flex min-w-0 flex-1 flex-col gap-3">
				<div class="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-1">
					<h2 class="min-w-0 text-lg leading-tight font-semibold text-ink">{name}</h2>
					{#if partId}<span class="shrink-0 font-mono text-sm text-ink-muted">{partId}</span>{/if}
				</div>
				<dl class="grid grid-cols-2 gap-x-6 gap-y-3 @2xl:grid-cols-3">
					{#each facts as fact (fact.label)}
						<div class="flex min-w-0 flex-col gap-0.5" title={fact.title}>
							<dt class="text-xs text-ink-muted">{fact.label}</dt>
							<dd
								class="flex min-w-0 items-center gap-1.5 text-sm {fact.mono
									? 'font-mono'
									: ''} {fact.valueClass ?? 'text-ink'}"
							>
								{#if fact.swatch}
									<span
										aria-hidden="true"
										class="size-4 shrink-0 rounded-check border border-line-strong"
										style:background-color={fact.swatch}
									></span>
								{/if}
								<span class="truncate">{fact.value}</span>
							</dd>
							{#if fact.note}
								<dd class="truncate text-xs text-ink-muted">{fact.note}</dd>
							{/if}
						</div>
					{/each}
				</dl>
			</div>
		</div>
		{#if summary?.correctable}
			<div class="border-t border-line px-(--pad-panel) py-4">
				<PieceCorrection layout="full" piece={summary} {endpointBase} onUpdated={onReviewed} />
			</div>
		{/if}
	</div>
</Panel>

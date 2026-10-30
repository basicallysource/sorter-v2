<script lang="ts">
	import PieceCorrection from '$lib/components/PieceCorrection.svelte';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import type { PieceSummary } from '$lib/pieces';
	import FrameStrip from './FrameStrip.svelte';
	import type { Fact, Frame } from './types';

	// The top of a piece's page: what you came to see. The pictures the camera
	// took (the ones that produced the result tinted) and Brickognize's picture
	// of the part, what the machine decided about it, and the review (the same
	// compact one the records list has) at the right. Everything that explains
	// how it got there is below, in the predictions and the details.
	let {
		name,
		partId,
		frames,
		framesNote,
		reference,
		facts,
		summary,
		endpointBase,
		onReviewed,
		onZoom
	}: {
		name: string;
		partId: string | null;
		frames: Frame[];
		framesNote: string;
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
	<div class="@container px-(--pad-panel) py-4">
		<div
			class="grid grid-cols-[minmax(0,1fr)] items-start gap-x-8 gap-y-4 @4xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] @6xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_24rem]"
		>
			<!-- The pictures -->
			<div class="flex min-w-0 flex-col gap-2">
				<p class="text-sm text-ink-muted">{framesNote}</p>
				{#if frames.length === 0}
					<p class="flex h-[4.75rem] items-center text-sm text-ink-muted">
						No burst frames for this piece.
					</p>
				{:else}
					<FrameStrip {frames} {onZoom} />
				{/if}
			</div>

			<!-- What the machine decided -->
			<div class="flex min-w-0 flex-col gap-2">
				<div class="flex min-w-0 items-baseline gap-2">
					<h2 class="min-w-0 truncate text-base font-semibold text-ink">{name}</h2>
					{#if partId}<span class="shrink-0 font-mono text-sm text-ink-muted">{partId}</span>{/if}
				</div>
				<div class="flex items-start gap-4">
					<dl
						class="grid min-w-0 flex-1 grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm"
					>
						{#each facts as fact (fact.label)}
							<dt class="text-ink-muted">{fact.label}</dt>
							<dd
								class="flex min-w-0 items-center gap-1.5 {fact.mono
									? 'font-mono'
									: ''} {fact.valueClass ?? 'text-ink'}"
								title={fact.title}
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
						{/each}
					</dl>
					{#if reference}
						<div class="flex shrink-0 flex-col items-center gap-0.5">
							<ImageZoom src={reference} label="Brickognize's picture of this part">
								<button
									type="button"
									aria-label="Enlarge Brickognize's picture of this part"
									class="block rounded-item p-1 transition-colors hover:bg-hover"
									onclick={() => onZoom(reference, `Brickognize: ${name}`)}
								>
									<PartImage src={reference} class="size-20" />
								</button>
							</ImageZoom>
							<span class="text-xs text-ink-muted">Brickognize</span>
						</div>
					{/if}
				</div>
			</div>

			<!-- The review -->
			{#if summary?.correctable}
				<div class="@4xl:col-span-2 @6xl:col-span-1">
					<PieceCorrection layout="compact" piece={summary} {endpointBase} onUpdated={onReviewed} />
				</div>
			{/if}
		</div>
	</div>
</Panel>

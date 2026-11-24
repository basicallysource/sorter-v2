<script lang="ts">
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Lane from './Lane.svelte';
	import PageParts, { statsOf } from './PageParts.svelte';
	import PredictionsTable from './PredictionsTable.svelte';
	import ReviewPreview from './ReviewPreview.svelte';
	import { CHANNEL_NAMES, CHANNELS, shotsOf, shotTime, type PieceView } from './model';

	// A piece's page in two columns. The pictures have the left one to
	// themselves, a section for each channel, and stay in sight while the right
	// one is read: what was decided, the review, the predictions, the rest.
	let { piece }: { piece: PieceView } = $props();

	const stats = $derived(statsOf(piece));
	const used = $derived(piece.shots.filter((shot) => shot.used).length);
</script>

<div class="@container">
	<div
		class="grid grid-cols-[minmax(0,1fr)] items-start gap-(--gap-panels) @5xl:grid-cols-[22.75rem_minmax(0,1fr)]"
	>
		<div class="@5xl:sticky @5xl:top-0">
			<Panel
				title="Pictures"
				description="{piece.shots
					.length} of this piece; {used} produced the result (the ones with a stroke)."
			>
				<div class="flex flex-col gap-4">
					{#each CHANNELS as channel (channel)}
						{@const shots = shotsOf(piece, channel)}
						<section class="flex flex-col gap-1.5">
							<div class="flex items-baseline justify-between gap-2">
								<span class="flex items-baseline gap-2">
									<span class="font-mono text-sm text-ink">{channel}</span>
									<span class="text-xs text-ink-muted">{CHANNEL_NAMES[channel]}</span>
								</span>
								<span class="num text-xs text-ink-muted">{shotTime(shots[0]) ?? ''}</span>
							</div>
							{#if shots.length === 0}
								<p class="text-sm text-ink-faint">No pictures linked to this piece here.</p>
							{:else}
								<Lane
									{shots}
									size={4.75}
									cols={4}
									rows={Math.min(3, Math.ceil(shots.length / 4))}
								/>
							{/if}
						</section>
					{/each}
				</div>
			</Panel>
		</div>

		<div class="flex min-w-0 flex-col gap-(--gap-panels)">
			<Panel flush>
				<div class="flex items-start gap-5 px-(--pad-panel) py-4">
					<ImageZoom
						src={piece.reference}
						label="Brickognize's picture of this part"
						class="shrink-0"
					>
						<PartImage src={piece.reference} class="size-28" />
					</ImageZoom>
					<div class="flex min-w-0 flex-1 flex-col gap-3">
						<div class="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
							<h2 class="text-lg leading-tight font-semibold text-ink">{piece.name}</h2>
							{#if piece.partId}
								<span class="font-mono text-sm text-ink-muted">{piece.partId}</span>
							{/if}
							<span class="self-center">
								<PieceStatusBadge status={piece.summary.classification_status} />
							</span>
						</div>
						<dl class="grid grid-cols-2 gap-x-6 gap-y-3 @3xl:grid-cols-5">
							{#each stats as stat (stat.label)}
								<div class="flex min-w-0 flex-col gap-0.5">
									<dt class="text-xs text-ink-muted">{stat.label}</dt>
									<dd class="flex min-w-0 items-center gap-1.5 text-sm text-ink">
										{#if stat.label === 'Color' && piece.color?.hex}
											<span
												aria-hidden="true"
												class="size-4 shrink-0 rounded-check border border-line-strong"
												style:background-color={piece.color.hex}
											></span>
										{/if}
										<span class="truncate {stat.mono ? 'font-mono' : ''}">{stat.value}</span>
									</dd>
									{#if stat.note}
										<dd class="truncate text-xs text-ink-muted">{stat.note}</dd>
									{/if}
								</div>
							{/each}
						</dl>
					</div>
				</div>
				<div class="border-t border-line px-(--pad-panel) py-4">
					<ReviewPreview {piece} layout="full" />
				</div>
			</Panel>
			<PredictionsTable {piece} />
			<PageParts />
		</div>
	</div>
</div>

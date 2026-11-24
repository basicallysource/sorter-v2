<script lang="ts">
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Lane from './Lane.svelte';
	import PageParts, { statsOf } from './PageParts.svelte';
	import PredictionsTable from './PredictionsTable.svelte';
	import ReviewPreview from './ReviewPreview.svelte';
	import { bestShot, CHANNEL_NAMES, CHANNELS, shotsOf, type PieceView, type Shot } from './model';

	// A piece's page built around the comparison: the camera's picture and
	// Brickognize's, large and at one size, with what was decided and the
	// review in a column beside them. Every picture is under the two, a line
	// for each channel; clicking one puts it in the large place.
	let { piece }: { piece: PieceView } = $props();

	let picked = $state<Shot | null>(null);
	const shown = $derived(
		(picked && piece.shots.find((shot) => shot.key === picked?.key)) ?? bestShot(piece)
	);
	const stats = $derived(statsOf(piece));
</script>

<Panel flush>
	<div class="@container">
		<div
			class="grid grid-cols-[minmax(0,1fr)] divide-line @5xl:grid-cols-[minmax(0,1fr)_25rem] @5xl:divide-x"
		>
			<div class="flex min-w-0 flex-col gap-5 p-(--pad-panel)">
				<div class="grid grid-cols-2 gap-4">
					<figure class="flex min-w-0 flex-col gap-1.5">
						<figcaption class="flex items-baseline gap-2 text-sm">
							<span class="font-medium text-ink">Camera</span>
							<span class="truncate text-xs text-ink-muted">{shown?.label ?? ''}</span>
						</figcaption>
						<div class="flex h-64 items-center justify-center">
							{#if shown}
								<img src={shown.src} alt="" class="block max-h-full max-w-full object-contain" />
							{/if}
						</div>
					</figure>
					<figure class="flex min-w-0 flex-col gap-1.5">
						<figcaption class="flex items-baseline gap-2 text-sm">
							<span class="font-medium text-ink">Brickognize</span>
							<span class="truncate text-xs text-ink-muted">
								{[piece.partId, piece.name].filter(Boolean).join(' ')}
							</span>
						</figcaption>
						<div class="flex h-64 items-center justify-center">
							<PartImage src={piece.reference} class="max-h-full max-w-full" />
						</div>
					</figure>
				</div>

				<div class="flex flex-col gap-1.5 border-t border-line pt-4">
					{#each CHANNELS as channel (channel)}
						{@const shots = shotsOf(piece, channel)}
						<div class="flex items-center gap-4">
							<span class="flex w-32 shrink-0 items-baseline gap-2 text-sm">
								<span class="font-mono text-ink">{channel}</span>
								<span class="truncate text-xs text-ink-muted">{CHANNEL_NAMES[channel]}</span>
							</span>
							{#if shots.length === 0}
								<span class="flex h-12 items-center text-sm text-ink-faint">No pictures linked</span
								>
							{:else}
								<Lane
									{shots}
									size={3}
									cols={12}
									selected={shown?.key}
									onpick={(shot) => (picked = shot)}
								/>
							{/if}
						</div>
					{/each}
				</div>
			</div>

			<div class="flex min-w-0 flex-col gap-4 p-(--pad-panel)">
				<div class="flex flex-col gap-1.5">
					<h2 class="text-lg leading-tight font-semibold text-ink">{piece.name}</h2>
					<div class="flex items-center gap-2">
						{#if piece.partId}
							<span class="font-mono text-sm text-ink-muted">{piece.partId}</span>
						{/if}
						<PieceStatusBadge status={piece.summary.classification_status} />
					</div>
				</div>
				<dl class="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-5 gap-y-1.5 text-sm">
					{#each stats as stat (stat.label)}
						<dt class="text-ink-muted">{stat.label}</dt>
						<dd class="flex min-w-0 items-baseline gap-2">
							{#if stat.label === 'Color' && piece.color?.hex}
								<span
									aria-hidden="true"
									class="size-4 shrink-0 self-center rounded-check border border-line-strong"
									style:background-color={piece.color.hex}
								></span>
							{/if}
							<span class="truncate text-ink {stat.mono ? 'font-mono' : ''}">{stat.value}</span>
							{#if stat.note}
								<span class="truncate text-xs text-ink-muted">{stat.note}</span>
							{/if}
						</dd>
					{/each}
				</dl>
				<div class="border-t border-line pt-4">
					<ReviewPreview {piece} layout="compact" />
				</div>
			</div>
		</div>
	</div>
</Panel>

<PredictionsTable {piece} />
<PageParts />

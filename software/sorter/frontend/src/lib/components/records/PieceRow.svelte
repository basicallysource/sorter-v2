<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import FlaskConical from '@lucide/svelte/icons/flask-conical';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import PieceCorrection from '$lib/components/PieceCorrection.svelte';
	import PieceProblems from '$lib/components/pieces/PieceProblems.svelte';
	import NoPieceImage from '$lib/components/pieces/NoPieceImage.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import { findLegoColor } from '$lib/pieces/colors';
	import { near } from '$lib/records/near';
	import type { PieceSummary } from '$lib/pieces';
	import type { DisplayImage, ImageState } from './piece-images';

	// One piece in the records list, a row of a divided list: its pictures, what
	// the machine did with it (and what went wrong, when anything did), and the
	// review at the right (the design system's compact PieceReview). Everything
	// else about the piece (every image, the attempts, the predictions) is on its
	// own page, one click away.
	let {
		piece,
		imgState,
		endpointBase,
		reclassifyOpen = false,
		onToggleReclassify,
		onPieceCorrected,
		onnear,
		onleave
	}: {
		piece: PieceSummary;
		imgState: ImageState | undefined;
		endpointBase: string;
		reclassifyOpen?: boolean;
		onToggleReclassify?: () => void;
		// Called with the fresh summary after a correction so the parent can
		// update its list in place without a refetch.
		onPieceCorrected?: (summary: PieceSummary) => void;
		// The row came near the screen, or left it: its pictures load when it is near.
		onnear?: () => void;
		onleave?: () => void;
	} = $props();

	// The pictures that produced the result get this many places in a row of
	// their own width, so the columns line up down the list; past them the last
	// place says how many more there are.
	const PLACES = 4;

	function formatWhen(ts: number | null | undefined): string | null {
		if (ts == null) return null;
		const d = new Date(ts * 1000);
		return d.toLocaleString(undefined, {
			...(d.getFullYear() === new Date().getFullYear() ? {} : { year: 'numeric' }),
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	}

	// As the dashboard's recent pieces and the piece's page write it, counted from
	// 0; the Bins page counts from 1, so the tooltip says it that way too.
	function formatBin(bin: PieceSummary['bin']): { text: string; title: string } | null {
		if (!bin) return null;
		return {
			text: `L${bin.x} · S${bin.y} · B${bin.z}`,
			title: `Layer ${bin.x + 1}, section ${bin.y + 1}, bin ${bin.z + 1} on the Bins page`
		};
	}

	function confidenceClass(conf: number): string {
		const pct = conf * 100;
		if (pct >= 90) return 'text-success-ink';
		if (pct >= 80) return 'text-warning-ink';
		if (pct >= 60) return 'text-warning-ink/70';
		return 'text-danger-ink';
	}

	// Sub-dollar pieces get an extra decimal so they don't collapse to "$0.00".
	function formatEstValue(v: number | null | undefined): string | null {
		if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) return null;
		return v >= 0.01 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`;
	}

	// The channel a picture was taken in. An unrecorded channel reads as unknown
	// rather than defaulting to C4: a link-match crop from C2 or C3 labelled "C4"
	// would be a lie about where the pixels came from.
	function channelLabel(img: DisplayImage): string {
		if (img.source === 'c4_burst') return 'C4';
		return img.channel === 2 || img.channel === 3 ? `C${img.channel}` : '—';
	}

	function sourceLabel(source: string | null | undefined, channel?: number | null): string {
		if (source === 'c4_burst') return 'C4 burst';
		if (source === 'link_match') {
			return channel === 2 || channel === 3 ? `Link match · C${channel}` : 'Link match';
		}
		if (source === 'upstream') {
			return channel === 2 || channel === 3 ? `Upstream · C${channel}` : 'Upstream';
		}
		return source || 'unknown';
	}

	// Chronological: left to right as the camera saw it.
	const sorted = $derived(
		imgState?.status === 'ok' ? [...imgState.images].sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0)) : []
	);
	// The list shows the pictures that produced the result; the rest are on the
	// piece's page (unshipped burst frames and link-match candidates are many).
	const shown = $derived(sorted.filter((img) => img.used));
	const lego_color = $derived(findLegoColor(piece.color_id, piece.color_name));
	const value = $derived(formatEstValue(piece.est_value));
	const bin = $derived(formatBin(piece.bin));
	const when = $derived(formatWhen(piece.seen_at));
	const crops = $derived(shown.length > PLACES ? shown.slice(0, PLACES - 1) : shown);
	// Never identified (a double feed, a piece lost on the way): no part to show
	// and nothing to review, so one short row instead of a card. Its pictures are
	// on its page.
	const bare = $derived(!piece.part_id && !piece.preview_url && !piece.correctable);
	const more = $derived(shown.length - crops.length);
	// Wide: the pictures, the outcome and the review side by side. A little less
	// wide: the review goes under them. Narrow: everything in one column.
	const columns = $derived(
		piece.correctable
			? 'grid-cols-[minmax(0,1fr)] @3xl:grid-cols-[27.5rem_minmax(0,1fr)] @6xl:grid-cols-[27.5rem_minmax(0,1fr)_24rem]'
			: 'grid-cols-[minmax(0,1fr)] @3xl:grid-cols-[27.5rem_minmax(0,1fr)]'
	);
</script>

<!-- A long list is mostly rows nobody is looking at: the browser skips drawing
	them, and the pictures of the ones near the screen are the ones that load. -->
{#if bare}
	<div
		class="flex items-center gap-3 px-(--pad-panel) py-2 [contain-intrinsic-size:auto_3.5rem] [content-visibility:auto]"
	>
		<a
			href={`/tracked/${piece.uuid}`}
			aria-label="Open the piece"
			class="-m-1 shrink-0 rounded-control p-1 hover:bg-hover"
		>
			<NoPieceImage class="h-8 w-auto text-ink-faint" />
		</a>
		<div class="flex min-w-0 flex-1 flex-col gap-0.5">
			<div class="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
				<span class="min-w-0 truncate text-sm font-semibold text-ink">
					{piece.part_name ?? piece.part_id ?? piece.uuid.slice(0, 8)}
				</span>
				<PieceStatusBadge status={piece.classification_status} dead={Boolean(piece.dead)} />
				{#if when}<span class="num text-xs text-ink-muted">{when}</span>{/if}
			</div>
			<PieceProblems problems={piece.problems} layout="line" />
		</div>
		<Button
			size="sm"
			variant="ghost"
			icon={ArrowRight}
			label="Open the piece"
			href={`/tracked/${piece.uuid}`}
		/>
	</div>
{:else}
	<div
		use:near={{ enter: () => onnear?.(), leave: () => onleave?.() }}
		class="@container px-(--pad-panel) py-3 [contain-intrinsic-size:auto_8rem] [content-visibility:auto]"
	>
		<div class="grid items-start gap-x-5 gap-y-3 {columns}">
			<!-- The pictures: what the camera saw, and what Brickognize shows for the part. -->
			<a
				href={`/tracked/${piece.uuid}`}
				aria-label="Open the piece"
				class="-m-1 flex min-h-20 flex-wrap items-start gap-1.5 rounded-control p-1 hover:bg-hover @3xl:flex-nowrap"
			>
				{#if imgState === undefined || imgState.status === 'loading'}
					<span class="flex gap-1.5" aria-busy="true">
						<Skeleton class="size-20" />
						<Skeleton class="size-20" />
					</span>
				{:else if shown.length === 0 && !imgState.stockUrl}
					<span
						class="flex h-20 items-center"
						title="No stored images for this piece: it was recorded before images were captured, or none were taken."
					>
						<NoPieceImage class="h-12 w-auto text-ink-faint" />
					</span>
				{:else}
					<span
						class="flex max-w-full flex-wrap gap-1.5 @3xl:w-[21.125rem] @3xl:shrink-0 @3xl:flex-nowrap"
					>
						{#each crops as img, i (i)}
							<ImageZoom
								src={img.src}
								label="{sourceLabel(img.source, img.channel)}: produced the result"
								class="shrink-0"
							>
								<span class="relative block size-20 shrink-0">
									<PartImage src={img.src} class="size-20" />
									<span
										class="dark num absolute bottom-0.5 left-0.5 rounded-badge bg-scrim px-1 text-xs font-medium text-ink"
									>
										{channelLabel(img)}
									</span>
								</span>
							</ImageZoom>
						{/each}
						{#if more > 0}
							<span
								class="num flex size-20 shrink-0 items-center justify-center text-sm text-ink-muted"
								title="{more} more pictures produced the result: they are on the piece's page"
							>
								+{more}
							</span>
						{/if}
						{#if shown.length === 0}
							<span
								class="flex h-20 items-center"
								title="No stored images for this piece: it was recorded before images were captured, or none were taken."
							>
								<NoPieceImage class="h-12 w-auto text-ink-faint" />
							</span>
						{/if}
					</span>
					{#if imgState.stockUrl}
						<span class="flex shrink-0 flex-col items-center gap-0.5 border-l border-line pl-2.5">
							<ImageZoom src={imgState.stockUrl} label="Brickognize's picture of this part">
								<PartImage src={imgState.stockUrl} class="size-20" />
							</ImageZoom>
							<span class="text-xs text-ink-muted">Brickognize</span>
						</span>
					{/if}
				{/if}
			</a>

			<!-- The outcome: the part, what the machine decided, and where it went. -->
			<div class="flex min-w-0 flex-col gap-1">
				<div class="flex min-w-0 items-center gap-2">
					<span class="min-w-0 truncate text-sm font-semibold text-ink">
						{piece.part_name ?? piece.part_id ?? piece.uuid.slice(0, 8)}
					</span>
					{#if piece.part_id && piece.part_name}
						<span class="shrink-0 font-mono text-xs text-ink-muted">{piece.part_id}</span>
					{/if}
					<span class="ml-auto flex shrink-0 items-center">
						{#if imgState?.status === 'ok' && imgState.origin === 'memory' && sorted.length > 0 && onToggleReclassify}
							<Button
								size="sm"
								variant={reclassifyOpen ? 'primary' : 'ghost'}
								icon={FlaskConical}
								label="Scratch reclassify: pick crops and re-run Brickognize (not recorded)"
								onclick={onToggleReclassify}
							/>
						{/if}
						<Button
							size="sm"
							variant="ghost"
							icon={ArrowRight}
							label="Open the piece"
							href={`/tracked/${piece.uuid}`}
						/>
					</span>
				</div>
				<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
					<span class="flex items-center gap-1.5">
						<PieceStatusBadge status={piece.classification_status} dead={Boolean(piece.dead)} />
					</span>
					{#if lego_color}
						<ColorChip name={lego_color.name} rgb={lego_color.hex} class="text-sm text-ink" />
					{:else if piece.color_name && piece.color_name !== 'Any Color'}
						<Badge>{piece.color_name}</Badge>
					{/if}
					{#if typeof piece.confidence === 'number'}
						<span
							class="num text-sm font-medium {confidenceClass(piece.confidence)}"
							title="How sure the identification was"
						>
							{Math.round(piece.confidence * 100)}%
						</span>
					{/if}
					{#if value}
						<span
							class="num text-sm text-ink"
							title="BrickLink moving-average price (Hive catalog)"
						>
							{value}
						</span>
					{/if}
				</div>
				<div class="flex flex-wrap items-center gap-x-3 text-xs text-ink-muted">
					{#if bin}<span class="font-mono" title={bin.title}>{bin.text}</span>{/if}
					{#if when}<span class="num">{when}</span>{/if}
					{#if imgState?.status === 'ok' && sorted.length > 0}
						<span
							class="num"
							title="Pictures that produced the result, of all stored for this piece"
						>
							{shown.length} of {sorted.length} pictures used
						</span>
					{/if}
				</div>
				<!-- What went wrong with it, when anything did: the names; the piece's page
				says what happened. -->
				<PieceProblems problems={piece.problems} layout="line" />
			</div>

			<!-- The review, at the right. -->
			{#if piece.correctable}
				<div class="@3xl:col-span-2 @6xl:col-span-1">
					<PieceCorrection layout="compact" {piece} {endpointBase} onUpdated={onPieceCorrected} />
				</div>
			{/if}
		</div>

		{#if reclassifyOpen && imgState?.status === 'ok' && imgState.origin === 'memory'}
			<div class="mt-3">
				<ReclassifyPanel
					{endpointBase}
					images={sorted
						.filter((img) => typeof img.b64 === 'string')
						.map((img) => ({
							image: img.b64 as string,
							label: sourceLabel(img.source, img.channel),
							used: img.used,
							score: img.score
						}))}
				/>
			</div>
		{/if}
	</div>
{/if}

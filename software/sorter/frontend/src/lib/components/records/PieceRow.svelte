<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import FlaskConical from '@lucide/svelte/icons/flask-conical';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import PieceCorrection from '$lib/components/PieceCorrection.svelte';
	import FrameStrip from '$lib/components/pieces/FrameStrip.svelte';
	import FrameTile from '$lib/components/pieces/FrameTile.svelte';
	import PieceProblems from '$lib/components/pieces/PieceProblems.svelte';
	import type { Frame } from '$lib/components/pieces/types';
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

	// One piece in the records list, a row of a divided list, laid out for the
	// question a reviewer answers: is this the part? The camera's picture and
	// Brickognize's sit side by side at one size. Beside them is what the
	// machine did with it (and what went wrong, when anything did) and, small
	// and on one line, every picture of the piece, each channel always in the
	// same place. The review is at the right (the design system's compact
	// PieceReview). Everything else about the piece (the attempts, the
	// predictions) is on its own page, one click away.
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

	// How many tiles each channel has on the line of small pictures, always:
	// three pictures or thirty take the same place, and the last tile says how
	// many more there are. The tiles shrink with the row, and a channel that
	// still has no room is left off whole, so a picture is never cut in half.
	const LANES = [
		{ channel: 'C4', places: 5 },
		{ channel: 'C3', places: 6 },
		{ channel: 'C2', places: 4 }
	];

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

	// Counted from 1, like the Bins page.
	function formatBin(bin: PieceSummary['bin']): { text: string; title: string } | null {
		if (!bin) return null;
		return {
			text: `L${bin.x + 1} · S${bin.y + 1} · B${bin.z + 1}`,
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
	const usedCount = $derived(sorted.filter((img) => img.used).length);
	// Every picture of the piece: the classification channel's first, then the
	// views of it found on C3 and on C2.
	function channelRank(img: DisplayImage): number {
		if (img.source === 'c4_burst') return 0;
		if (img.channel === 3) return 1;
		if (img.channel === 2) return 2;
		return 3;
	}
	const all = $derived<Frame[]>(
		[...sorted]
			.sort((a, b) => channelRank(a) - channelRank(b))
			.map((img, i) => ({
				key: String(i),
				src: img.src,
				ts: img.ts ?? null,
				label: [
					sourceLabel(img.source, img.channel),
					img.source === 'link_match' && typeof img.score === 'number'
						? `${(img.score * 100).toFixed(1)}% match`
						: null,
					img.used ? 'produced the result' : null
				]
					.filter(Boolean)
					.join(' · '),
				used: img.used,
				channel: channelLabel(img),
				sharpness:
					typeof img.sharpness === 'number' && Number.isFinite(img.sharpness)
						? String(Math.round(img.sharpness))
						: null
			}))
	);
	// The camera's picture beside Brickognize's: the first one that produced
	// the result, else the piece's first picture.
	const best = $derived(all.find((frame) => frame.used) ?? all[0] ?? null);
	const loading = $derived(imgState === undefined || imgState.status === 'loading');
	// The record names Brickognize's picture, so it is there before the piece's own are.
	const reference = $derived(
		(imgState?.status === 'ok' ? imgState.stockUrl : null) ?? piece.preview_url ?? null
	);
	const lego_color = $derived(findLegoColor(piece.color_id, piece.color_name));
	const value = $derived(formatEstValue(piece.est_value));
	const bin = $derived(formatBin(piece.bin));
	const when = $derived(formatWhen(piece.seen_at));
	// Never identified (a double feed, a piece lost on the way): no part to show
	// and nothing to review, so one short row instead of a card. Its pictures are
	// on its page.
	const bare = $derived(!piece.part_id && !piece.preview_url && !piece.correctable);
	// Wide: the two pictures, the outcome and the review side by side. A little less
	// wide: the review goes under them. Narrow: everything in one column.
	const columns = $derived(
		piece.correctable
			? 'grid-cols-[minmax(0,1fr)] @3xl:grid-cols-[13.75rem_minmax(0,1fr)] @6xl:grid-cols-[13.75rem_minmax(0,1fr)_24rem]'
			: 'grid-cols-[minmax(0,1fr)] @3xl:grid-cols-[13.75rem_minmax(0,1fr)]'
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
		class="@container px-(--pad-panel) py-3 [contain-intrinsic-size:auto_9rem] [content-visibility:auto]"
	>
		<div class="grid items-center gap-x-5 gap-y-3 {columns}">
			<!-- The two pictures a reviewer looks between: the camera's and Brickognize's. -->
			<a
				href={`/tracked/${piece.uuid}`}
				aria-label="Open the piece"
				class="-m-1 flex gap-3 rounded-control p-1 hover:bg-hover"
			>
				<span class="flex flex-col items-center gap-1">
					{#if loading}
						<span aria-busy="true"><Skeleton class="size-[6.5rem]" /></span>
					{:else if best}
						<FrameTile frame={best} size={6.5} mark={false} />
					{:else}
						<span
							class="flex size-[6.5rem] items-center justify-center bg-well"
							title="No stored images for this piece: it was recorded before images were captured, or none were taken."
						>
							<NoPieceImage class="h-12 w-auto text-ink-faint" />
						</span>
					{/if}
					<span class="text-xs text-ink-muted">Camera</span>
				</span>
				<span class="flex flex-col items-center gap-1">
					<ImageZoom src={reference} label="Brickognize's picture of this part">
						<PartImage src={reference} class="size-[6.5rem]" />
					</ImageZoom>
					<span class="text-xs text-ink-muted">Brickognize</span>
				</span>
			</a>

			<div class="flex min-w-0 flex-col gap-2.5">
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
					<div class="flex min-w-0 items-center gap-x-3 overflow-hidden whitespace-nowrap">
						<span class="flex shrink-0 items-center gap-1.5">
							<PieceStatusBadge status={piece.classification_status} dead={Boolean(piece.dead)} />
						</span>
						{#if lego_color}
							<ColorChip
								name={lego_color.name}
								rgb={lego_color.hex}
								class="shrink-0 text-sm text-ink"
							/>
						{:else if piece.color_name && piece.color_name !== 'Any Color'}
							<Badge>{piece.color_name}</Badge>
						{/if}
						{#if typeof piece.confidence === 'number'}
							<span
								class="num shrink-0 text-sm font-medium {confidenceClass(piece.confidence)}"
								title="How sure the identification was"
							>
								{Math.round(piece.confidence * 100)}%
							</span>
						{/if}
						{#if value}
							<span
								class="num shrink-0 text-sm text-ink"
								title="BrickLink moving-average price (Hive catalog)"
							>
								{value}
							</span>
						{/if}
					</div>
					<div
						class="flex min-w-0 items-center gap-x-3 overflow-hidden text-xs whitespace-nowrap text-ink-muted"
					>
						{#if bin}<span class="shrink-0 font-mono" title={bin.title}>{bin.text}</span>{/if}
						{#if when}<span class="num shrink-0">{when}</span>{/if}
						{#if imgState?.status === 'ok' && sorted.length > 0}
							<span
								class="num shrink-0"
								title="Pictures that produced the result, of all stored for this piece"
							>
								{usedCount} of {sorted.length} pictures used
							</span>
						{/if}
					</div>
					<!-- What went wrong with it, when anything did: the names; the piece's page
					says what happened. -->
					<PieceProblems problems={piece.problems} layout="line" />
				</div>

				<!-- Every picture of the piece, small: a channel's tiles are always in the
				same place, and the line keeps its height while the pictures load. -->
				<div
					class="flex h-[calc(2rem*var(--tile-scale)+0.25rem)] flex-wrap items-center gap-x-3 overflow-hidden [--tile-scale:0.6] @4xl:[--tile-scale:0.75] @6xl:[--tile-scale:0.6] @7xl:[--tile-scale:0.75] @[84rem]:[--tile-scale:1]"
				>
					{#each LANES as lane (lane.channel)}
						<span class="flex h-full shrink-0 items-center gap-1">
							<span class="font-mono text-xs text-ink-muted">{lane.channel}</span>
							<FrameStrip
								frames={all.filter((frame) => frame.channel === lane.channel)}
								size={2}
								cols={lane.places}
							/>
						</span>
					{/each}
				</div>
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

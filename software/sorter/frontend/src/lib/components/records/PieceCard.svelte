<script lang="ts">
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import FlaskConical from '@lucide/svelte/icons/flask-conical';
	import ImageInfoBadge from '$lib/components/ImageInfoBadge.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import PieceCorrection from '$lib/components/PieceCorrection.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import { findLegoColor } from '$lib/pieces/colors';
	import { onColor } from '$lib/theme';
	import type { ClassificationAttempt, ClassificationAttemptStrategy } from '$lib/api/events';
	import type { PieceSummary } from '$lib/pieces';
	import type { DisplayImage, ImageState } from './piece-images';

	let {
		piece,
		imgState,
		endpointBase,
		reclassifyOpen = false,
		onToggleReclassify,
		onPieceCorrected,
		liveCrop = null
	}: {
		piece: PieceSummary;
		imgState: ImageState | undefined;
		endpointBase: string;
		reclassifyOpen?: boolean;
		onToggleReclassify?: () => void;
		// Called with the fresh summary after a correction so the parent can
		// update its list in place without a refetch.
		onPieceCorrected?: (summary: PieceSummary) => void;
		// Newest captured crop off the live socket — shown for in-flight pieces
		// that haven't been hydrated from the detail endpoint yet.
		liveCrop?: string | null;
	} = $props();

	function formatTimestamp(ts: number | null | undefined): string {
		if (ts == null) return '—';
		const d = new Date(ts * 1000);
		return d.toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatBin(bin: PieceSummary['bin']): string {
		if (!bin) return '—';
		return `L${bin.x} · S${bin.y} · B${bin.z}`;
	}

	function formatConfidence(c: number | null | undefined): string {
		if (c == null) return '—';
		return `${(c * 100).toFixed(0)}%`;
	}

	function confidenceClass(conf: number | null | undefined): string {
		if (conf == null) return 'text-ink-muted';
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


	// Corner badge for an image's channel. An unrecorded channel reads as
	// unknown rather than defaulting to C4 — a link-match crop from C2/C3
	// labelled "C4 burst" is a lie about where the pixels came from.
	function sourceBadge(img: DisplayImage): { label: string; cls: string } {
		const ch = img.channel;
		if (img.source === 'c4_burst') {
			return { label: 'C4', cls: 'border-line bg-surface text-ink-muted' };
		}
		const label = ch === 2 || ch === 3 ? `C${ch}` : '—';
		return { label, cls: 'border-warning/60 bg-warning-soft text-warning-ink' };
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

	// Badge shown on the result header when classification needed a retry. null
	// for the normal first-try (combined) path, so it only ever flags the
	// interesting case.
	function strategyBadge(
		strategy: ClassificationAttemptStrategy | null | undefined
	): { label: string } | null {
		if (!strategy || strategy === 'combined') return null;
		if (strategy === 'single_burst') return { label: 'WON · BURST ALONE' };
		return { label: `WON · ${strategy}` };
	}

	// One chip per Brickognize attempt for the attempts strip. The applied one is
	// highlighted; misses and errors read muted.
	function attemptChip(a: ClassificationAttempt): { text: string; cls: string } {
		const name = a.label ?? a.strategy;
		const outcome = a.error
			? 'error'
			: a.found
				? `${((a.confidence ?? 0) * 100).toFixed(0)}%`
				: 'miss';
		const cls = a.applied
			? 'border-primary/60 bg-primary-soft text-primary-ink'
			: 'border-line bg-surface text-ink-muted';
		return { text: `${name}: ${outcome}${a.applied ? ' ✓' : ''}`, cls };
	}

	// Per-image visual state: produced the applied result, sent-then-dropped on a
	// retry, or never shipped.
	function imageState(img: DisplayImage): 'used' | 'dropped' | 'unsent' {
		if (img.used) return 'used';
		if (img.excluded_from_result) return 'dropped';
		return 'unsent';
	}

	// Chronological — read left-to-right as what the camera saw.
	function sortImages(images: DisplayImage[]): DisplayImage[] {
		return [...images].sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0));
	}

	// Age of a pic in seconds relative to when the owning KnownObject was created.
	// C4 burst frames are snapped just after creation.
	function imageAgeLabel(img: DisplayImage, objCreatedAt: number | null): string | null {
		if (typeof img.created_at !== 'number' || objCreatedAt === null) return null;
		const delta = objCreatedAt - img.created_at;
		const mag = Math.abs(delta).toFixed(1);
		if (Math.abs(delta) < 0.05) return '0.0s';
		return delta > 0 ? `${mag}s before` : `${mag}s after`;
	}

	function imageInfoRows(
		img: DisplayImage,
		objCreatedAt: number | null
	): { label: string; value: string }[] {
		const shipped = img.used
			? 'Yes — used for result'
			: img.excluded_from_result
				? 'Sent, lost to a higher-scoring request'
				: 'No';
		const rows: { label: string; value: string }[] = [
			{ label: 'Source', value: sourceLabel(img.source, img.channel) },
			{ label: 'Shipped', value: shipped }
		];
		const age = imageAgeLabel(img, objCreatedAt);
		if (age !== null) {
			rows.push({ label: 'Age', value: age });
		}
		return rows;
	}

	const sorted = $derived(imgState?.status === 'ok' ? sortImages(imgState.images) : []);
	// The records list is a compact scan of many pieces, so it shows only the
	// images that actually produced the result. Everything else the piece
	// carries -- unshipped burst frames, link-match candidates from C2/C3 --
	// belongs on the detail page, not here; showing all of them turned each row
	// into 40+ thumbnails of unrelated pieces.
	const shown = $derived(sorted.filter((img) => img.used));
	const objCreatedAt = $derived(imgState?.createdAt ?? null);
	const lego_color = $derived(findLegoColor(piece.color_id, piece.color_name));
	const est_value_text = $derived(formatEstValue(piece.est_value));
</script>

<div class="border border-line bg-surface">
	<!-- Result header -->
	<div class="flex flex-wrap items-center gap-2 border-b border-line bg-well px-3 py-2">
		<PieceStatusBadge status={piece.classification_status} dead={Boolean(piece.dead)} />

		<span class="truncate text-sm font-semibold text-ink">
			{piece.part_name ?? piece.part_id ?? piece.uuid.slice(0, 8)}
		</span>
		{#if piece.part_id && piece.part_name}
			<span class="font-mono text-xs text-ink-muted">{piece.part_id}</span>
		{/if}

		{#if typeof piece.confidence === 'number'}
			<span class="text-sm font-semibold num {confidenceClass(piece.confidence)}">
				{formatConfidence(piece.confidence)}
			</span>
		{/if}

		{#if est_value_text}
			<span
				class="text-sm font-semibold num text-success-ink"
				title="BrickLink moving-average price (Hive catalog)"
			>
				{est_value_text}
			</span>
		{/if}

		{#if imgState?.status === 'ok'}
			{@const sb = strategyBadge(imgState.strategy)}
			{#if sb}
				<span
					class="inline-flex items-center border border-info/60 bg-info-soft px-1.5 py-0.5 text-xs font-semibold text-info-ink"
					title="A single-image Brickognize request outscored the fused combined call"
				>
					{sb.label}
				</span>
			{/if}
		{/if}

		{#if lego_color}
			<span
				class="inline-flex items-center border border-line px-1.5 py-0.5 text-xs font-semibold"
				style:background-color={lego_color.hex}
				style:color={onColor(lego_color.hex)}
			>
				{lego_color.name}
			</span>
		{:else if piece.color_name && piece.color_name !== 'Any Color'}
			<span
				class="inline-flex items-center border border-line bg-surface px-1.5 py-0.5 text-xs text-ink-muted"
			>
				{piece.color_name}
			</span>
		{/if}

		<span class="ml-auto flex items-center gap-3 text-xs text-ink-muted">
			{#if imgState?.status === 'ok' && sorted.length > 0}
				<span class="num" title="Images that produced the result, of all stored for this piece">
					{shown.length} of {sorted.length} used
				</span>
			{/if}
			<span class="font-mono">{formatBin(piece.bin)}</span>
			<span class="num">{formatTimestamp(piece.seen_at)}</span>
			{#if imgState?.status === 'ok' && imgState.origin === 'memory' && sorted.length > 0 && onToggleReclassify}
				<button
					type="button"
					onclick={onToggleReclassify}
					class="inline-flex items-center gap-1 {reclassifyOpen
						? 'text-warning-ink'
						: 'text-ink-muted hover:text-warning-ink'}"
					title="Scratch reclassify — pick crops and re-run Brickognize (not recorded)"
				>
					<FlaskConical size={13} />
				</button>
			{/if}
			<a
				href={`/tracked/${piece.uuid}`}
				class="inline-flex items-center gap-1 text-ink-muted hover:text-primary-ink"
				title="Open piece detail"
			>
				<ExternalLink size={13} />
			</a>
		</span>
	</div>

	<!-- Attempts strip — the parallel requests (combined + singles) -->
	{#if imgState?.status === 'ok' && (imgState.attempts?.length ?? 0) > 1}
		<div class="flex flex-wrap items-center gap-1.5 border-b border-line bg-well px-3 py-1.5">
			<span class="text-xs font-semibold text-ink-muted"> Attempts </span>
			{#each imgState.attempts ?? [] as a, ai (ai)}
				{@const chip = attemptChip(a)}
				<span class="inline-flex items-center border px-1.5 py-0.5 text-xs {chip.cls}">
					{chip.text}
				</span>
			{/each}
		</div>
	{/if}

	<!-- Image contact sheet -->
	<div class="p-3">
		{#if liveCrop && imgState === undefined}
			<div class="flex flex-wrap gap-2">
				<div class="flex flex-col border border-line bg-white">
					<div class="h-28 w-28 bg-white">
						<img src={liveCrop} alt="live crop" class="h-full w-full object-contain" />
					</div>
					<div class="flex items-center justify-center border-t border-line px-1.5 py-1">
						<span
							class="inline-flex items-center text-xs font-semibold text-primary-ink"
						>
							Live
						</span>
					</div>
				</div>
			</div>
		{:else if imgState?.status === 'loading' || imgState === undefined}
			<div class="flex flex-wrap gap-2">
				{#each Array(4) as _, i (i)}
					<Skeleton class="h-28 w-28" />
				{/each}
			</div>
		{:else if imgState.status === 'missing' || (shown.length === 0 && !imgState.stockUrl)}
			<div class="text-sm text-ink-muted">
				No stored images for this piece (recorded before image capture existed, or none taken).
			</div>
		{:else}
			<div class="flex items-start gap-4">
				<div class="flex flex-1 flex-wrap gap-2">
					{#each shown as img, i (i)}
						{@const badge = sourceBadge(img)}
						{@const src = img.src}
						{@const state = imageState(img)}
						<div
							class="relative flex flex-col border bg-white {state === 'used'
								? 'border-2 border-primary'
								: state === 'dropped'
									? 'border-2 border-danger/60'
									: 'border-line'}"
							title={state === 'used'
								? 'Used — produced the applied result'
								: state === 'dropped'
									? 'Sent in a parallel request that lost — thrown out'
									: 'Captured, not shipped'}
						>
							<div class="h-16 w-16 bg-white {state === 'dropped' ? 'opacity-50' : ''}">
								{#if src}
									<img {src} alt={img.source} class="h-full w-full object-contain" loading="lazy" />
								{/if}
							</div>
							<div class="flex items-center justify-between gap-1 border-t border-line px-1.5 py-1">
								<div class="flex items-center gap-1">
									{#if src}
										<ImageInfoBadge {src} rows={imageInfoRows(img, objCreatedAt)} />
									{/if}
									<span
										class="inline-flex items-center border px-1 py-0.5 text-xs font-semibold {badge.cls}"
									>
										{badge.label}
									</span>
								</div>
								{#if state === 'dropped'}
									<span
										class="inline-flex items-center border border-danger/60 bg-danger-soft px-1 py-0.5 text-xs font-semibold text-danger-ink"
									>
										Dropped
									</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
				{#if imgState.stockUrl}
					<div class="ml-auto flex flex-col border border-line bg-white">
						<div class="h-28 w-28 bg-white">
							<img
								src={imgState.stockUrl}
								alt="Brickognize reference"
								class="h-full w-full object-contain"
								loading="lazy"
							/>
						</div>
						<div class="flex items-center justify-center border-t border-line px-1.5 py-1">
							<span
								class="inline-flex items-center text-xs font-semibold text-ink-muted"
							>
								Brickognize
							</span>
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	{#if piece.correctable}
		<div class="border-t border-line bg-well p-3">
			<PieceCorrection {piece} {endpointBase} onUpdated={onPieceCorrected} />
		</div>
	{/if}

	{#if reclassifyOpen && imgState?.status === 'ok' && imgState.origin === 'memory'}
		<div class="border-t border-line p-3">
			<ReclassifyPanel
				endpointBase={endpointBase}
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

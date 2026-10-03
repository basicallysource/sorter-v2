<script lang="ts">
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import FlaskConical from '@lucide/svelte/icons/flask-conical';
	import ImageInfoBadge from '$lib/components/ImageInfoBadge.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import PieceCorrection from '$lib/components/PieceCorrection.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
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
	function sourceBadge(img: DisplayImage): { label: string; tone: 'neutral' | 'warning' } {
		const ch = img.channel;
		if (img.source === 'c4_burst') return { label: 'C4', tone: 'neutral' };
		return { label: ch === 2 || ch === 3 ? `C${ch}` : '—', tone: 'warning' };
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
		if (strategy === 'single_burst') return { label: 'Won by the burst alone' };
		return { label: `Won by ${String(strategy).replace(/_/g, ' ')}` };
	}

	// One chip per Brickognize attempt for the attempts strip. The applied one is
	// highlighted; misses and errors read muted.
	function attemptChip(a: ClassificationAttempt): { text: string; applied: boolean } {
		const name = a.label ?? a.strategy;
		const outcome = a.error
			? 'error'
			: a.found
				? `${((a.confidence ?? 0) * 100).toFixed(0)}%`
				: 'miss';
		return { text: `${name}: ${outcome}${a.applied ? ' ✓' : ''}`, applied: Boolean(a.applied) };
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
			? 'Yes, used for the result'
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

<Panel>
	<div class="flex flex-col gap-3">
		<!-- The result -->
		<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
			<PieceStatusBadge status={piece.classification_status} dead={Boolean(piece.dead)} />

			<span class="truncate text-sm font-semibold text-ink">
				{piece.part_name ?? piece.part_id ?? piece.uuid.slice(0, 8)}
			</span>
			{#if piece.part_id && piece.part_name}
				<span class="font-mono text-xs text-ink-muted">{piece.part_id}</span>
			{/if}

			{#if typeof piece.confidence === 'number'}
				<span class="num text-sm font-medium {confidenceClass(piece.confidence)}">
					{formatConfidence(piece.confidence)}
				</span>
			{/if}

			{#if est_value_text}
				<span class="num text-sm text-ink" title="BrickLink moving-average price (Hive catalog)">
					{est_value_text}
				</span>
			{/if}

			{#if imgState?.status === 'ok'}
				{@const sb = strategyBadge(imgState.strategy)}
				{#if sb}
					<span title="A single-image Brickognize request outscored the fused combined call">
						<Badge tone="info">{sb.label}</Badge>
					</span>
				{/if}
			{/if}

			<!-- A part's color is data, so its chip is that color. -->
			{#if lego_color}
				<span
					class="inline-flex h-(--size-badge) items-center rounded-badge border border-line px-(--pad-badge) text-xs font-medium"
					style:background-color={lego_color.hex}
					style:color={onColor(lego_color.hex)}
				>
					{lego_color.name}
				</span>
			{:else if piece.color_name && piece.color_name !== 'Any Color'}
				<Badge>{piece.color_name}</Badge>
			{/if}

			<span class="ml-auto flex items-center gap-3 text-xs text-ink-muted">
				{#if imgState?.status === 'ok' && sorted.length > 0}
					<span class="num" title="Images that produced the result, of all stored for this piece">
						{shown.length} of {sorted.length} used
					</span>
				{/if}
				<span class="font-mono">{formatBin(piece.bin)}</span>
				<span class="num">{formatTimestamp(piece.seen_at)}</span>
				<span class="flex items-center">
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
						icon={ExternalLink}
						label="Open the piece"
						href={`/tracked/${piece.uuid}`}
					/>
				</span>
			</span>
		</div>

		<!-- The parallel requests: combined and single -->
		{#if imgState?.status === 'ok' && (imgState.attempts?.length ?? 0) > 1}
			<div class="flex flex-wrap items-center gap-1.5">
				<span class="label">Attempts</span>
				{#each imgState.attempts ?? [] as a, ai (ai)}
					{@const chip = attemptChip(a)}
					<Badge tone={chip.applied ? 'primary' : 'neutral'}>{chip.text}</Badge>
				{/each}
			</div>
		{/if}

		<!-- The pictures -->
		{#if liveCrop && imgState === undefined}
			<div class="flex flex-wrap gap-2">
				<div class="flex flex-col items-center gap-1">
					<img src={liveCrop} alt="live crop" class="size-28 rounded-item object-contain" />
					<span class="text-xs font-medium text-primary-ink">Live</span>
				</div>
			</div>
		{:else if imgState?.status === 'loading' || imgState === undefined}
			<div class="flex flex-wrap gap-2">
				{#each Array(4) as _, i (i)}
					<Skeleton class="size-28" />
				{/each}
			</div>
		{:else if imgState.status === 'missing' || (shown.length === 0 && !imgState.stockUrl)}
			<p class="text-sm text-ink-muted">
				No stored images for this piece: it was recorded before images were captured, or none were taken.
			</p>
		{:else}
			<div class="flex items-start gap-4">
				<div class="flex flex-1 flex-wrap gap-2">
					{#each shown as img, i (i)}
						{@const badge = sourceBadge(img)}
						{@const src = img.src}
						{@const state = imageState(img)}
						<div
							class="flex flex-col gap-1 rounded-control p-1 {state === 'used'
								? 'bg-primary-soft'
								: state === 'dropped'
									? 'bg-danger-soft'
									: ''}"
							title={state === 'used'
								? 'Used: produced the applied result'
								: state === 'dropped'
									? 'Sent in a parallel request that lost, so thrown out'
									: 'Captured, not shipped'}
						>
							<div class="size-16 rounded-item {state === 'dropped' ? 'opacity-50' : ''}">
								{#if src}
									<img {src} alt={img.source} class="size-full object-contain" loading="lazy" />
								{/if}
							</div>
							<div class="flex flex-wrap items-center gap-1">
								{#if src}<ImageInfoBadge {src} rows={imageInfoRows(img, objCreatedAt)} />{/if}
								<Badge tone={badge.tone}>{badge.label}</Badge>
								{#if state === 'dropped'}<Badge tone="danger">Dropped</Badge>{/if}
							</div>
						</div>
					{/each}
				</div>
				{#if imgState.stockUrl}
					<div class="ml-auto flex flex-col items-center gap-1">
						<img
							src={imgState.stockUrl}
							alt="Brickognize reference"
							class="size-28 rounded-item object-contain"
							loading="lazy"
						/>
						<span class="text-xs text-ink-muted">Brickognize</span>
					</div>
				{/if}
			</div>
		{/if}

		{#if piece.correctable}
			<div class="rounded-control bg-well p-3">
				<PieceCorrection {piece} {endpointBase} onUpdated={onPieceCorrected} />
			</div>
		{/if}

		{#if reclassifyOpen && imgState?.status === 'ok' && imgState.origin === 'memory'}
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
		{/if}
	</div>
</Panel>

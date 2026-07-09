<script lang="ts">
	import { ExternalLink, FlaskConical } from 'lucide-svelte';
	import ImageInfoBadge from '$lib/components/ImageInfoBadge.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import { Skeleton } from '$lib/components/primitives';
	import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';
	import type { ClassificationAttempt, ClassificationAttemptStrategy } from '$lib/api/events';
	import type { PieceSummary } from '$lib/pieces';
	import type { DisplayImage, ImageState } from './piece-images';

	let {
		piece,
		imgState,
		endpointBase,
		reclassifyOpen = false,
		onToggleReclassify,
		liveCrop = null
	}: {
		piece: PieceSummary;
		imgState: ImageState | undefined;
		endpointBase: string;
		reclassifyOpen?: boolean;
		onToggleReclassify?: () => void;
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
		if (conf == null) return 'text-text-muted';
		const pct = conf * 100;
		if (pct >= 90) return 'text-success';
		if (pct >= 80) return 'text-warning';
		if (pct >= 60) return 'text-warning/70';
		return 'text-danger';
	}

	// Sub-dollar pieces get an extra decimal so they don't collapse to "$0.00".
	function formatEstValue(v: number | null | undefined): string | null {
		if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) return null;
		return v >= 0.01 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`;
	}

	function lookupLegoColor(
		color_id: string | null | undefined,
		color_name: string | null | undefined
	): LegoColor | null {
		if (color_id) {
			const by_id = LEGO_COLORS.find((c) => c.id === color_id);
			if (by_id) return by_id;
		}
		if (color_name) {
			const lower = color_name.toLowerCase();
			const by_name = LEGO_COLORS.find((c) => c.name.toLowerCase() === lower);
			if (by_name) return by_name;
		}
		return null;
	}

	function sourceBadge(img: DisplayImage): { label: string; cls: string } {
		const ch = img.channel;
		if (img.source === 'upstream') {
			// Upstream crops come from C2 or C3; fall back to "C2/3" for older
			// records captured before the channel was recorded.
			const label = ch === 2 || ch === 3 ? `C${ch}` : 'C2/3';
			return { label, cls: 'border-warning/60 bg-warning/[0.12] text-warning' };
		}
		return { label: 'C4', cls: 'border-border bg-surface text-text-muted' };
	}

	// Badge shown on the result header when classification needed a retry. null
	// for the normal first-try (combined) path, so it only ever flags the
	// interesting case.
	function strategyBadge(
		strategy: ClassificationAttemptStrategy | null | undefined
	): { label: string } | null {
		if (!strategy || strategy === 'combined') return null;
		if (strategy === 'single_burst') return { label: 'WON · BURST ALONE' };
		if (strategy === 'single_upstream') return { label: 'WON · UPSTREAM ALONE' };
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
			? 'border-primary/60 bg-primary/[0.12] text-primary'
			: 'border-border bg-surface text-text-muted';
		return { text: `${name}: ${outcome}${a.applied ? ' ✓' : ''}`, cls };
	}

	// Per-image visual state: produced the applied result, sent-then-dropped on a
	// retry, or never shipped.
	function imageState(img: DisplayImage): 'used' | 'dropped' | 'unsent' {
		if (img.used) return 'used';
		if (img.excluded_from_result) return 'dropped';
		return 'unsent';
	}

	// C4 burst frames first, then upstream matches — read left-to-right as
	// "what the camera saw" followed by "what we pulled from upstream".
	function sortImages(images: DisplayImage[]): DisplayImage[] {
		return [...images].sort((a, b) => {
			if (a.source !== b.source) return a.source === 'c4_burst' ? -1 : 1;
			return (a.ts ?? 0) - (b.ts ?? 0);
		});
	}

	function imageCounts(images: DisplayImage[]): { c4: number; upstream: number } {
		let c4 = 0;
		let upstream = 0;
		for (const img of images) {
			if (img.source === 'upstream') upstream += 1;
			else c4 += 1;
		}
		return { c4, upstream };
	}

	// Age of a pic in seconds relative to when the owning KnownObject was created.
	// Upstream crops are captured before the piece reaches C4 (object creation),
	// so they read "before"; C4 burst frames are snapped just after creation.
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
			{ label: 'Source', value: img.source === 'upstream' ? 'Upstream (C2/C3)' : 'C4 burst' },
			{ label: 'Shipped', value: shipped }
		];
		if (img.source === 'upstream' && typeof img.score === 'number') {
			rows.push({ label: 'Similarity', value: `${(img.score * 100).toFixed(0)}%` });
		}
		const age = imageAgeLabel(img, objCreatedAt);
		if (age !== null) {
			rows.push({ label: 'Age', value: age });
		}
		return rows;
	}

	const sorted = $derived(imgState?.status === 'ok' ? sortImages(imgState.images) : []);
	const counts = $derived(imageCounts(sorted));
	const objCreatedAt = $derived(imgState?.createdAt ?? null);
	const lego_color = $derived(lookupLegoColor(piece.color_id, piece.color_name));
	const est_value_text = $derived(formatEstValue(piece.est_value));
</script>

<div class="border border-border bg-surface">
	<!-- Result header -->
	<div class="flex flex-wrap items-center gap-2 border-b border-border bg-bg px-3 py-2">
		<PieceStatusBadge status={piece.classification_status} dead={Boolean(piece.dead)} />

		<span class="truncate text-sm font-semibold text-text">
			{piece.part_name ?? piece.part_id ?? piece.uuid.slice(0, 8)}
		</span>
		{#if piece.part_id && piece.part_name}
			<span class="font-mono text-xs text-text-muted">{piece.part_id}</span>
		{/if}

		{#if typeof piece.confidence === 'number'}
			<span class="text-sm font-semibold tabular-nums {confidenceClass(piece.confidence)}">
				{formatConfidence(piece.confidence)}
			</span>
		{/if}

		{#if est_value_text}
			<span
				class="text-sm font-semibold tabular-nums text-success"
				title="BrickLink moving-average price (local catalog)"
			>
				{est_value_text}
			</span>
		{/if}

		{#if imgState?.status === 'ok'}
			{@const sb = strategyBadge(imgState.strategy)}
			{#if sb}
				<span
					class="inline-flex items-center border border-info/60 bg-info/[0.12] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-info"
					title="A single-image Brickognize request outscored the fused combined call"
				>
					{sb.label}
				</span>
			{/if}
		{/if}

		{#if lego_color}
			<span
				class="inline-flex items-center border border-border px-1.5 py-0.5 text-xs font-semibold"
				style:background-color={lego_color.hex}
				style:color={lego_color.contrast === 'white' ? '#ffffff' : '#000000'}
			>
				{lego_color.name}
			</span>
		{:else if piece.color_name && piece.color_name !== 'Any Color'}
			<span
				class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted"
			>
				{piece.color_name}
			</span>
		{/if}

		<span class="ml-auto flex items-center gap-3 text-xs text-text-muted">
			{#if imgState?.status === 'ok' && sorted.length > 0}
				<span class="tabular-nums">{counts.c4} C4 · {counts.upstream} upstream</span>
			{/if}
			<span class="font-mono">{formatBin(piece.bin)}</span>
			<span class="tabular-nums">{formatTimestamp(piece.seen_at)}</span>
			{#if imgState?.status === 'ok' && imgState.origin === 'memory' && sorted.length > 0 && onToggleReclassify}
				<button
					type="button"
					onclick={onToggleReclassify}
					class="inline-flex items-center gap-1 {reclassifyOpen
						? 'text-warning'
						: 'text-text-muted hover:text-warning'}"
					title="Scratch reclassify — pick crops and re-run Brickognize (not recorded)"
				>
					<FlaskConical size={13} />
				</button>
			{/if}
			<a
				href={`/tracked/${piece.uuid}`}
				class="inline-flex items-center gap-1 text-text-muted hover:text-primary"
				title="Open piece detail"
			>
				<ExternalLink size={13} />
			</a>
		</span>
	</div>

	<!-- Attempts strip — the parallel requests (combined + singles) -->
	{#if imgState?.status === 'ok' && (imgState.attempts?.length ?? 0) > 1}
		<div class="flex flex-wrap items-center gap-1.5 border-b border-border bg-bg px-3 py-1.5">
			<span class="text-xs font-semibold uppercase tracking-wider text-text-muted"> Attempts </span>
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
				<div class="flex flex-col border border-border bg-white">
					<div class="h-28 w-28 bg-white">
						<img src={liveCrop} alt="live crop" class="h-full w-full object-contain" />
					</div>
					<div class="flex items-center justify-center border-t border-border px-1.5 py-1">
						<span
							class="inline-flex items-center text-xs font-semibold uppercase tracking-wider text-primary"
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
		{:else if imgState.status === 'missing' || (sorted.length === 0 && !imgState.stockUrl)}
			<div class="text-sm text-text-muted">
				No stored images for this piece (recorded before image capture existed, or none taken).
			</div>
		{:else}
			<div class="flex items-start gap-4">
				<div class="flex flex-1 flex-wrap gap-2">
					{#each sorted as img, i (i)}
						{@const badge = sourceBadge(img)}
						{@const src = img.src}
						{@const state = imageState(img)}
						<div
							class="relative flex flex-col border bg-white {state === 'used'
								? 'border-2 border-primary'
								: state === 'dropped'
									? 'border-2 border-danger/60'
									: 'border-border'}"
							title={state === 'used'
								? 'Used — produced the applied result'
								: state === 'dropped'
									? 'Sent in a parallel request that lost — thrown out'
									: 'Captured, not shipped'}
						>
							<div class="h-28 w-28 bg-white {state === 'dropped' ? 'opacity-50' : ''}">
								{#if src}
									<img {src} alt={img.source} class="h-full w-full object-contain" loading="lazy" />
								{/if}
							</div>
							<div class="flex items-center justify-between gap-1 border-t border-border px-1.5 py-1">
								<div class="flex items-center gap-1">
									{#if src}
										<ImageInfoBadge {src} rows={imageInfoRows(img, objCreatedAt)} />
									{/if}
									<span
										class="inline-flex items-center border px-1 py-0.5 text-xs font-semibold uppercase tracking-wider {badge.cls}"
									>
										{badge.label}
									</span>
								</div>
								{#if state === 'dropped'}
									<span
										class="inline-flex items-center border border-danger/60 bg-danger/[0.12] px-1 py-0.5 text-xs font-semibold uppercase tracking-wider text-danger"
									>
										Dropped
									</span>
								{:else if img.source === 'upstream' && typeof img.score === 'number'}
									<span class="text-xs tabular-nums text-text-muted">
										{(img.score * 100).toFixed(0)}%
									</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
				{#if imgState.stockUrl}
					<div class="ml-auto flex flex-col border border-border bg-white">
						<div class="h-28 w-28 bg-white">
							<img
								src={imgState.stockUrl}
								alt="Brickognize reference"
								class="h-full w-full object-contain"
								loading="lazy"
							/>
						</div>
						<div class="flex items-center justify-center border-t border-border px-1.5 py-1">
							<span
								class="inline-flex items-center text-xs font-semibold uppercase tracking-wider text-text-muted"
							>
								Brickognize
							</span>
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	{#if reclassifyOpen && imgState?.status === 'ok' && imgState.origin === 'memory'}
		<div class="border-t border-border p-3">
			<ReclassifyPanel
				endpointBase={endpointBase}
				images={sorted
					.filter((img) => typeof img.b64 === 'string')
					.map((img) => ({
						image: img.b64 as string,
						label: img.source === 'upstream' ? 'Upstream' : 'C4 burst',
						used: img.used,
						score: img.score
					}))}
			/>
		</div>
	{/if}
</div>

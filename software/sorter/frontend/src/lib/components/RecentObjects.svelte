<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import type { KnownObjectData } from '$lib/api/events';
	import Spinner from './Spinner.svelte';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';

	type LifecyclePhase = 'tracking' | 'capturing' | 'classified' | 'distributed';

	const MAX_DELIVERED_PIECES = 8;
	const RECENT_TERMINAL_DEDUPE_WINDOW_S = 15;
	const C4_DROP_ANGLE_DEG = 30;

	const ctx = getMachineContext();
	sortingProfileStore.load();

	function hasLocalPreview(obj: KnownObjectData): boolean {
		return Boolean(
			obj.latest_captured_crop ||
				obj.thumbnail ||
				obj.top_image ||
				obj.bottom_image ||
				obj.drop_snapshot
		);
	}

	function hasCapturingEvidence(obj: KnownObjectData): boolean {
		// Anything proving the capture/classify pipeline has engaged: a snap
		// timestamp, a locally-stored crop or thumbnail, or any part data.
		return Boolean(
			obj.carousel_snapping_started_at ||
				obj.classified_at ||
				obj.part_id ||
				hasLocalPreview(obj)
		);
	}

	function lifecyclePhase(obj: KnownObjectData): LifecyclePhase {
		// "Distributing" (in motion) still renders as Classified. Only fully-
		// delivered pieces flip to 'distributed'.
		if (isTerminalPiece(obj)) return 'distributed';
		if (
			obj.classification_status === 'classified' ||
			obj.classification_status === 'unknown' ||
			obj.classification_status === 'not_found' ||
			obj.classification_status === 'multi_drop_fail' ||
			obj.classified_at
		) {
			return 'classified';
		}
		if (hasCapturingEvidence(obj)) return 'capturing';
		// Reliably tracked by the carousel tracker but no capture has started
		// yet — show the piece as soon as we have an identity for it.
		if (obj.tracked_global_id !== null && obj.tracked_global_id !== undefined) {
			return 'tracking';
		}
		return 'capturing';
	}

	function shouldShowInRecentPieces(obj: KnownObjectData): boolean {
		// Recent Pieces is the C4 timeline: only show pieces that have
		// actually been observed on the classification channel. Anything
		// still upstream (C2/C3) is hidden until it lands on C4. The
		// machine-manager buffer applies the same gate, so this is a
		// belt-and-braces check for any stale entries.
		return obj.first_carousel_seen_ts != null;
	}

	function isTerminalPiece(obj: KnownObjectData): boolean {
		return obj.stage === 'distributed' || obj.distributed_at != null;
	}

	function isUnresolvedTerminal(obj: KnownObjectData): boolean {
		return (
			obj.classification_status === 'unknown' ||
			obj.classification_status === 'not_found' ||
			obj.classification_status === 'multi_drop_fail'
		);
	}

	function hasTerminalEvidence(obj: KnownObjectData): boolean {
		if (!isTerminalPiece(obj)) return true;
		if (!isUnresolvedTerminal(obj)) return true;
		return Boolean(
			obj.latest_captured_crop ||
				obj.top_image ||
				obj.bottom_image ||
				(obj.thumbnail && obj.classified_at)
		);
	}

	function physicalPieceKey(obj: KnownObjectData): string {
		const gid = obj.tracked_global_id;
		return gid !== null && gid !== undefined ? `track:${gid}` : `uuid:${obj.uuid}`;
	}

	function lastEventTs(obj: KnownObjectData): number {
		return obj.updated_at ?? obj.created_at ?? 0;
	}

	function terminalTs(obj: KnownObjectData): number {
		return obj.distributed_at ?? obj.updated_at ?? obj.classified_at ?? obj.created_at ?? 0;
	}

	function c4ArrivalTs(obj: KnownObjectData): number {
		return obj.first_carousel_seen_ts ?? obj.carousel_detected_confirmed_at ?? obj.created_at ?? 0;
	}

	function normalizeDeg(value: number): number {
		const normalized = value % 360;
		return normalized < 0 ? normalized + 360 : normalized;
	}

	function circularDiffDeg(a: number, b: number): number {
		return ((normalizeDeg(a) - normalizeDeg(b) + 540) % 360) - 180;
	}

	function c4ExitApproachOffset(obj: KnownObjectData): number | null {
		const exit_offset = obj.classification_channel_exit_offset_deg;
		if (typeof exit_offset === 'number' && Number.isFinite(exit_offset)) return exit_offset;
		const center = obj.classification_channel_zone_center_deg;
		if (typeof center !== 'number' || !Number.isFinite(center)) return null;
		// Negative means still approaching the configured drop/exit line;
		// values closer to zero are physically closer to being distributed.
		return circularDiffDeg(center, C4_DROP_ANGLE_DEG);
	}

	function dedupeByPhysicalPiece(objects: KnownObjectData[]): KnownObjectData[] {
		const seen = new Set<string>();
		const deduped: KnownObjectData[] = [];
		for (const obj of objects) {
			const key = physicalPieceKey(obj);
			if (seen.has(key)) continue;
			seen.add(key);
			deduped.push(obj);
		}
		return deduped;
	}

	function sortActiveC4Pieces(a: KnownObjectData, b: KnownObjectData): number {
		const aOffset = c4ExitApproachOffset(a);
		const bOffset = c4ExitApproachOffset(b);
		if (aOffset !== null && bOffset !== null && aOffset !== bOffset) {
			return aOffset - bOffset;
		}
		const arrivalDiff = c4ArrivalTs(b) - c4ArrivalTs(a);
		if (arrivalDiff !== 0) return arrivalDiff;
		return lastEventTs(b) - lastEventTs(a);
	}

	const activeOnC4 = $derived.by(() => {
		const all = (ctx.machine?.recentObjects ?? []).filter(shouldShowInRecentPieces);
		// If a terminal event and a stale active split briefly coexist, keep
		// the terminal row and suppress the old active identity.
		const recent_terminal_keys = new Set<string>();
		const now_s = Date.now() / 1000;
		for (const o of all) {
			if (!isTerminalPiece(o)) continue;
			const ts = terminalTs(o);
			if (now_s - ts > RECENT_TERMINAL_DEDUPE_WINDOW_S) continue;
			recent_terminal_keys.add(physicalPieceKey(o));
		}

		const freshest_first = all
			.filter((o) => !isTerminalPiece(o))
			.filter((o) => !recent_terminal_keys.has(physicalPieceKey(o)))
			.sort((a, b) => lastEventTs(b) - lastEventTs(a));

		return dedupeByPhysicalPiece(freshest_first).sort(sortActiveC4Pieces);
	});

	const deliveredHistory = $derived.by(() => {
		const freshest_first = (ctx.machine?.recentObjects ?? [])
			.filter(shouldShowInRecentPieces)
			.filter(isTerminalPiece)
			.filter(hasTerminalEvidence)
			.sort((a, b) => terminalTs(b) - terminalTs(a));
		// Newest terminal piece sits directly under the distributed line.
		return dedupeByPhysicalPiece(freshest_first).slice(0, MAX_DELIVERED_PIECES);
	});

	function dataImageUrl(payload: string | null | undefined): string | null {
		return payload ? `data:image/jpeg;base64,${payload}` : null;
	}

	function capturedCropUrl(obj: KnownObjectData, phase: LifecyclePhase): string | null {
		// Prefer the newest object crop; full-frame/drop snapshots are only a
		// final fallback once no crop-like evidence exists.
		const crop_like =
			dataImageUrl(obj.latest_captured_crop) ??
			dataImageUrl(obj.top_image) ??
			dataImageUrl(obj.bottom_image);
		if (crop_like) return crop_like;
		if (phase === 'tracking' || phase === 'capturing') return null;
		return (
			dataImageUrl(obj.thumbnail) ??
			dataImageUrl(obj.drop_snapshot)
		);
	}

	function formatBin(bin: [unknown, unknown, unknown]): string {
		return `L${bin[0]} · S${bin[1]} · B${bin[2]}`;
	}

	function formatRelativeTime(ts: number | null | undefined): string {
		if (!ts) return '';
		const diff = Math.max(0, Date.now() / 1000 - ts);
		if (diff < 60) return `${Math.round(diff)}s`;
		if (diff < 3600) return `${Math.round(diff / 60)}m`;
		return `${Math.round(diff / 3600)}h`;
	}

	function confidenceClass(conf: number): string {
		// 4-tier grading per spec. There is no dedicated orange brand token, so
		// 80-89 and 60-79 both use the warning amber — 60-79 uses a dimmer
		// opacity to visually distinguish "marginal" from "good".
		const pct = conf * 100;
		if (pct >= 90) return 'text-success';
		if (pct >= 80) return 'text-warning';
		if (pct >= 60) return 'text-warning/70';
		return 'text-danger';
	}

	const PHASE_LABEL: Record<LifecyclePhase, string> = {
		tracking: 'Tracking',
		capturing: 'Capturing',
		classified: 'Classified',
		distributed: 'Distributed'
	};

	function phaseChipClass(phase: LifecyclePhase): string {
		// Sharp-edged chip, border + faint tinted bg + solid text. No rounded-*.
		if (phase === 'tracking') return 'border-text-muted bg-text-muted/10 text-text-muted';
		if (phase === 'capturing') return 'border-primary bg-primary/10 text-primary';
		if (phase === 'classified') return 'border-success bg-success/10 text-success';
		return 'border-border bg-surface text-text-muted';
	}

	// Normalize a color id or name to a LEGO_COLORS entry. Brickognize and
	// BrickLink both use slug-ish ids (e.g. "white", "light-bluish-gray"), and
	// `color_name` is the canonical display name. Try id first, fall back to
	// name match (case-insensitive).
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

	// Tick loop so relative timestamps refresh without new events.
	let now_tick = $state(0);
	$effect(() => {
		const id = setInterval(() => (now_tick += 1), 1000);
		return () => clearInterval(id);
	});
	$effect(() => {
		void now_tick;
	});
</script>

{#snippet pieceCard(obj: KnownObjectData)}
	{@const phase = lifecyclePhase(obj)}
	{@const captured = capturedCropUrl(obj, phase)}
	{@const preview = obj.brickognize_preview_url ?? null}
	{@const reference_src = preview}
	{@const cat_name = obj.category_id
		? sortingProfileStore.getCategoryName(obj.category_id)
		: null}
	{@const is_unknown =
		obj.classification_status === 'unknown' ||
		obj.classification_status === 'not_found'}
	{@const is_multi_drop = obj.classification_status === 'multi_drop_fail'}
	{@const is_classified_ok = !is_unknown && !is_multi_drop && Boolean(reference_src)}
	{@const ts =
		obj.distributed_at ??
		obj.classified_at ??
		obj.first_carousel_seen_ts ??
		obj.updated_at ??
		obj.created_at}

	{@const lego_color =
		!is_unknown && !is_multi_drop && obj.color_name && obj.color_name !== 'Any Color'
			? lookupLegoColor(obj.color_id, obj.color_name)
			: null}
	<!-- Brickognize supplies `part_name` whenever it has a hit; fall back to
	     the part id when there's no name. -->
	{@const resolved_name = obj.part_name ?? null}
	{@const has_name = Boolean(resolved_name) && !is_unknown && !is_multi_drop}
	{@const primary_text = is_multi_drop
		? 'Multi drop — rejected'
		: is_unknown
			? obj.classification_status === 'not_found'
				? 'Not recognized by Brickognize'
				: 'Unknown piece'
			: has_name
				? resolved_name!
				: (obj.part_id ?? obj.uuid.slice(0, 8))}
	{@const primary_class = is_multi_drop
		? 'text-danger'
		: is_unknown
			? 'text-text-muted'
			: 'text-text'}

	<a
		href={`/tracked/${obj.uuid}`}
		class="block border border-border bg-bg transition-colors hover:border-primary/70"
	>
		<div class="flex items-start gap-3 p-2">
			<!-- Primary image well (hover-swap only on classified+recognized) -->
			<div class="relative h-20 w-20 flex-shrink-0 border border-border bg-white group">
				{#if is_classified_ok && captured}
					<!-- Brickognize reference is primary; captured crop on hover -->
					<img
						src={reference_src}
						alt="reference"
						class="absolute inset-0 h-full w-full object-contain transition-opacity duration-150 group-hover:opacity-0"
					/>
					<img
						src={captured}
						alt="captured"
						class="absolute inset-0 h-full w-full object-contain opacity-0 transition-opacity duration-150 group-hover:opacity-100"
					/>
				{:else if is_classified_ok && !captured}
					<img src={reference_src} alt="reference" class="h-full w-full object-contain" />
				{:else if captured}
					<img src={captured} alt="captured" class="h-full w-full object-contain" />
				{:else}
					<div class="flex h-full w-full items-center justify-center">
						<Spinner />
					</div>
				{/if}
				{#if phase === 'capturing' || phase === 'tracking'}
					<div class="absolute -right-1 -top-1">
						<Spinner />
					</div>
				{/if}
			</div>

			<div class="flex min-w-0 flex-1 flex-col gap-1">
				<div class="flex items-baseline justify-between gap-2">
					<span class="truncate text-sm font-semibold {primary_class}">
						{primary_text}
					</span>
					{#if typeof obj.confidence === 'number' && !is_unknown && !is_multi_drop}
						<span class="flex-shrink-0 text-sm font-semibold tabular-nums {confidenceClass(obj.confidence)}">
							{(obj.confidence * 100).toFixed(0)}%
						</span>
					{/if}
				</div>

				{#if has_name && obj.part_id}
					<div class="truncate font-mono text-xs text-text-muted">{obj.part_id}</div>
				{:else if phase === 'tracking' && !is_unknown && !is_multi_drop}
					<div class="text-xs text-text-muted">Tracked on carousel…</div>
				{:else if phase === 'capturing' && !is_unknown && !is_multi_drop}
					<div class="text-xs text-text-muted">Capturing on C4…</div>
				{/if}

				<div class="mt-0.5 flex flex-wrap items-center gap-1.5">
					<!-- Phase chip -->
					<span
						class="inline-flex items-center border px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider {phaseChipClass(
							phase
						)}"
					>
						{PHASE_LABEL[phase]}
					</span>

					<!-- Color chip — sharp-edged, filled with the LEGO hex -->
					{#if lego_color}
						<span
							class="inline-flex items-center border border-border px-1.5 py-0.5 text-xs font-semibold"
							style:background-color={lego_color.hex}
							style:color={lego_color.contrast === 'white' ? '#ffffff' : '#000000'}
						>
							{lego_color.name}
						</span>
					{:else if obj.color_name && obj.color_name !== 'Any Color' && !is_unknown && !is_multi_drop}
						<span class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted">
							{obj.color_name}
						</span>
					{/if}

					<!-- Category (plain, de-emphasized) -->
					{#if cat_name && !is_unknown && !is_multi_drop}
						<span class="text-xs text-text-muted">{cat_name}</span>
					{/if}

					<!-- Bin chip — monospace, neutral surface -->
					{#if obj.destination_bin && phase === 'distributed'}
						<span
							class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs tabular-nums text-text"
						>
							{is_unknown || is_multi_drop ? 'discard ' : ''}{formatBin(obj.destination_bin)}
						</span>
					{:else if phase === 'distributed' && (is_unknown || is_multi_drop)}
						<span class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text-muted">
							discard bin
						</span>
					{/if}
				</div>
			</div>
		</div>
	</a>
{/snippet}

<div class="setup-card-shell flex h-full flex-col border">
	<div class="setup-card-header px-3 py-2 text-sm font-medium text-text">Recent Pieces</div>
	<div class="flex-1 overflow-y-auto">
		{#if activeOnC4.length === 0 && deliveredHistory.length === 0}
			<div class="p-3 text-center text-sm text-text-muted">No pieces yet</div>
		{:else}
			<div class="flex flex-col gap-1 p-1">
				<!-- Active C4 pieces: farthest from exit at top, nearest exit above line. -->
				{#each activeOnC4 as obj (obj.uuid)}
					{@render pieceCard(obj)}
				{/each}

				<!-- Exit divider -->
				<div class="flex items-center gap-2 py-1 select-none">
					<div class="h-px flex-1 bg-border"></div>
					<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">distributed</span>
					<div class="h-px flex-1 bg-border"></div>
				</div>

				<!-- Delivered/rejected history: newest-first directly under the line. -->
				{#each deliveredHistory as obj (obj.uuid)}
					{@render pieceCard(obj)}
				{/each}
			</div>
		{/if}
	</div>
</div>

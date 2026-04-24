<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import type { KnownObjectData } from '$lib/api/events';
	import Spinner from './Spinner.svelte';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import {
		capturedCropUrl,
		recentPhysicalKeyOrNull,
		lifecyclePhase,
		shouldShowInRecentPieces,
		type LifecyclePhase
	} from '$lib/recent-pieces';

	const ctx = getMachineContext();
	type LiveC4Track = {
		global_id: number | null;
		angle_deg: number | null;
		score?: number | null;
		hit_count?: number | null;
		last_seen_ts?: number | null;
		confirmed_real?: boolean;
		ghost?: boolean;
	};
	type RecentPieceDisplay = KnownObjectData & { __liveOnly?: boolean };

	let liveC4Tracks = $state<Map<number, LiveC4Track>>(new Map());
	let liveC4TrackPollAvailable = $state(false);
	let rtTrackPollTimer: ReturnType<typeof setInterval> | null = null;

	onMount(() => {
		void sortingProfileStore.load().catch(() => {});
		void refreshLiveC4Tracks();
		rtTrackPollTimer = setInterval(() => void refreshLiveC4Tracks(), 500);
	});

	onDestroy(() => {
		if (rtTrackPollTimer !== null) clearInterval(rtTrackPollTimer);
	});

	async function refreshLiveC4Tracks() {
		try {
			const res = await fetch(`${effectiveBase()}/api/rt/tracks/c4_feed`);
			if (!res.ok) {
				liveC4TrackPollAvailable = false;
				liveC4Tracks = new Map();
				return;
			}
			const payload = await res.json();
			const tracks = Array.isArray(payload?.tracks) ? payload.tracks : [];
			const next = new Map<number, LiveC4Track>();
			for (const track of tracks) {
				const gid = track?.global_id;
				if (typeof gid !== 'number') continue;
				if (track?.ghost === true) continue;
				if (track?.confirmed_real === false) continue;
				next.set(gid, {
					global_id: gid,
					angle_deg: typeof track?.angle_deg === 'number' ? track.angle_deg : null,
					score: typeof track?.score === 'number' ? track.score : null,
					hit_count: typeof track?.hit_count === 'number' ? track.hit_count : null,
					last_seen_ts: typeof track?.last_seen_ts === 'number' ? track.last_seen_ts : null,
					confirmed_real: Boolean(track?.confirmed_real),
					ghost: Boolean(track?.ghost)
				});
			}
			liveC4Tracks = next;
			liveC4TrackPollAvailable = true;
		} catch {
			liveC4TrackPollAvailable = false;
			liveC4Tracks = new Map();
		}
	}

	function isDisplayableLiveTrack(track: LiveC4Track): boolean {
		if (track.ghost === true) return false;
		if (track.confirmed_real === true) return true;
		const hits = typeof track.hit_count === 'number' ? track.hit_count : 0;
		const score = typeof track.score === 'number' ? track.score : 0;
		return hits >= 2 && score >= 0.35;
	}

	function wrapDeg(value: number): number {
		let wrapped = ((value + 180) % 360 + 360) % 360 - 180;
		if (wrapped === -180) wrapped = 180;
		return wrapped;
	}

	function liveTrackFor(obj: KnownObjectData): LiveC4Track | null {
		const gid = obj.tracked_global_id;
		if (typeof gid !== 'number') return null;
		return liveC4Tracks.get(gid) ?? null;
	}

	function c4AngleDeg(obj: KnownObjectData): number | null {
		const live = liveTrackFor(obj);
		if (typeof live?.angle_deg === 'number') return live.angle_deg;
		return typeof obj.classification_channel_zone_center_deg === 'number'
			? obj.classification_channel_zone_center_deg
			: null;
	}

	function exitDistanceDeg(obj: KnownObjectData): number | null {
		const angle = c4AngleDeg(obj);
		const exit = obj.classification_channel_exit_deg;
		if (typeof angle !== 'number' || typeof exit !== 'number') return null;
		return Math.abs(wrapDeg(angle - exit));
	}

	function objectForLiveTrack(
		track: LiveC4Track,
		objectsByGid: Map<number, KnownObjectData>
	): RecentPieceDisplay | null {
		const gid = track.global_id;
		if (typeof gid !== 'number') return null;
		const existing = objectsByGid.get(gid);
		if (existing && lifecyclePhase(existing) !== 'distributed') return existing;
		const now = Date.now() / 1000;
		return {
			__liveOnly: true,
			uuid: String(gid),
			created_at: track.last_seen_ts ?? now,
			updated_at: track.last_seen_ts ?? now,
			stage: 'registered',
			classification_status: 'pending',
			tracked_global_id: gid,
			first_carousel_seen_ts: track.last_seen_ts ?? now,
			classification_channel_zone_state: 'active',
			classification_channel_zone_center_deg: track.angle_deg,
			classification_channel_exit_deg: 30
		};
	}

	// "Upcoming" = pieces currently tracked on C4, ordered along the polar
	// path toward the exit: top = farthest from exit, bottom = next to drop.
	const upcoming = $derived.by(() => {
		const all = ctx.machine?.recentObjects ?? [];
		const objectsByGid = new Map<number, KnownObjectData>();
		for (const obj of all) {
			const gid = obj.tracked_global_id;
			if (typeof gid !== 'number') continue;
			if (lifecyclePhase(obj) === 'distributed') continue;
			objectsByGid.set(gid, obj);
		}
		const list = Array.from(liveC4Tracks.values())
			.filter(isDisplayableLiveTrack)
			.map((track) => objectForLiveTrack(track, objectsByGid))
			.filter((obj): obj is RecentPieceDisplay => obj !== null);
		list.sort((a, b) => {
			const da = exitDistanceDeg(a);
			const db = exitDistanceDeg(b);
			if (da !== null && db !== null && da !== db) return db - da;
			if (da !== null && db === null) return -1;
			if (da === null && db !== null) return 1;
			return (
				(a.first_carousel_seen_ts ?? a.created_at ?? 0) -
				(b.first_carousel_seen_ts ?? b.created_at ?? 0)
			);
		});
		// Collapse identity splits: same physical piece may surface as
		// multiple KnownObjects while C4 tracking settles. Keyed off
		// tracked_global_id (stable across rotations with BoTSORT) or uuid.
		const seen_keys = new Set<string>();
		const deduped: RecentPieceDisplay[] = [];
		for (const o of list) {
			const key = recentPhysicalKeyOrNull(o);
			if (key === null) continue;
			if (seen_keys.has(key)) continue;
			seen_keys.add(key);
			deduped.push(o);
		}
		return deduped.slice(0, 5);
	});

	const delivered = $derived.by(() => {
		const list = (ctx.machine?.recentObjects ?? [])
			.filter(shouldShowInRecentPieces)
			.filter((o) => lifecyclePhase(o) === 'distributed');
		// Newest-first (most recently delivered directly under the exit line).
		list.sort(
			(a, b) => (b.distributed_at ?? b.updated_at ?? 0) - (a.distributed_at ?? a.updated_at ?? 0)
		);
		return list.slice(0, 5);
	});

	function formatBin(bin: [unknown, unknown, unknown]): string {
		return `L${bin[0]} · S${bin[1]} · B${bin[2]}`;
	}

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
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
	{@const captured = capturedCropUrl(obj, effectiveBase())}
	{@const preview = obj.brickognize_preview_url ?? null}
	{@const reference_src = preview}
	{@const cat_name = obj.category_id ? sortingProfileStore.getCategoryName(obj.category_id) : null}
	{@const category_label = cat_name ?? obj.part_category ?? obj.category_id ?? null}
	{@const bin_label = obj.destination_bin ? formatBin(obj.destination_bin) : obj.bin_id}
	{@const is_unknown =
		obj.classification_status === 'unknown' || obj.classification_status === 'not_found'}
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
			<div class="group relative h-20 w-20 flex-shrink-0 border border-border bg-white">
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
					<div class="absolute -top-1 -right-1">
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
						<span
							class="flex-shrink-0 text-sm font-semibold tabular-nums {confidenceClass(
								obj.confidence
							)}"
						>
							{(obj.confidence * 100).toFixed(0)}%
						</span>
					{/if}
				</div>

				{#if has_name && obj.part_id}
					<div class="truncate font-mono text-xs text-text-muted">{obj.part_id}</div>
				{:else if phase === 'tracking' && !is_unknown && !is_multi_drop}
					<div class="text-xs text-text-muted">Tracked on C4…</div>
				{:else if phase === 'capturing' && !is_unknown && !is_multi_drop}
					<div class="text-xs text-text-muted">Capturing on C4…</div>
				{/if}

				<div class="mt-0.5 flex flex-wrap items-center gap-1.5">
					<!-- Phase chip -->
					<span
						class="inline-flex items-center border px-1.5 py-0.5 text-xs font-semibold tracking-wider uppercase {phaseChipClass(
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
						<span
							class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted"
						>
							{obj.color_name}
						</span>
					{/if}

					<!-- Category (plain, de-emphasized) -->
					{#if category_label && !is_unknown && !is_multi_drop}
						<span class="text-xs text-text-muted">{category_label}</span>
					{/if}

					<!-- Bin chip — monospace, neutral surface -->
					{#if bin_label}
						<span
							class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text tabular-nums"
						>
							{is_unknown || is_multi_drop ? 'discard ' : ''}{bin_label}
						</span>
					{:else if phase === 'distributed' && (is_unknown || is_multi_drop)}
						<span
							class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text-muted"
						>
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
		{#if upcoming.length === 0 && delivered.length === 0}
			<div class="p-3 text-center text-sm text-text-muted">No pieces yet</div>
		{:else}
			<div class="flex flex-col gap-1 p-1">
				<!-- Upcoming queue: farthest-to-nearest, with next-to-distribute at the divider. -->
				{#each upcoming as obj (obj.uuid)}
					{@render pieceCard(obj)}
				{/each}

				<!-- Exit divider -->
				<div class="flex items-center gap-2 py-1 select-none">
					<div class="h-px flex-1 bg-border"></div>
					<span class="text-xs font-semibold tracking-wider text-text-muted uppercase"
						>distributed</span
					>
					<div class="h-px flex-1 bg-border"></div>
				</div>

				<!-- Delivered (newest-first directly under the line) -->
				{#each delivered as obj (obj.uuid)}
					{@render pieceCard(obj)}
				{/each}
			</div>
		{/if}
	</div>
</div>

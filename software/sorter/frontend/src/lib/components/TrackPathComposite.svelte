<script lang="ts">
	// TrackPathComposite — renders the pie-chart-style composite visualization
	// for a single feeder-tracker global id. Fetches
	// /api/feeder/tracking/history/<id> and draws one SVG per segment, with the
	// piece's sector snapshots clipped into their original angular wedges on
	// top of a dimmed snapshot of the channel.
	//
	// Extracted from routes/tracked/[globalId=integer]/+page.svelte so the
	// per-piece detail page (`/tracked/[uuid]`) can reuse it. The integer page
	// retains its full classroom interface (manual recognize, per-segment
	// reclassification); this component is intentionally "render-only".
	import { onDestroy, onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';

	type Props = {
		globalId: number;
		/** Captured-ts subset (seconds) of crops that were shipped to Brickognize.
		 *  Any sector snapshot whose captured_ts is within a ~5ms tolerance of
		 *  any entry gets a primary-color outline. */
		usedCropTs?: number[];
	};

	let { globalId, usedCropTs = [] }: Props = $props();

	type PathPoint = [number, number, number];

	type SectorSnapshot = {
		sector_index: number;
		start_angle_deg: number;
		end_angle_deg: number;
		captured_ts: number;
		bbox_x: number;
		bbox_y: number;
		width: number;
		height: number;
		jpeg_b64: string;
		r_inner?: number;
		r_outer?: number;
		piece_jpeg_b64?: string;
	};

	type Segment = {
		source_role: string;
		handoff_from: string | null;
		first_seen_ts: number;
		last_seen_ts: number;
		duration_s: number;
		hit_count: number;
		path_points: number;
		snapshot_width: number;
		snapshot_height: number;
		snapshot_jpeg_b64: string;
		path: PathPoint[];
		channel_center_x: number | null;
		channel_center_y: number | null;
		channel_radius_inner: number | null;
		channel_radius_outer: number | null;
		sector_count: number;
		sector_snapshots: SectorSnapshot[];
	};

	type Detail = {
		global_id: number;
		segments: Segment[];
		live?: boolean;
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	let detail = $state<Detail | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(false);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	const TS_TOLERANCE_S = 0.005;

	function isUsedCrop(captured_ts: number): boolean {
		if (!usedCropTs || usedCropTs.length === 0) return false;
		for (const ts of usedCropTs) {
			if (Math.abs(ts - captured_ts) <= TS_TOLERANCE_S) return true;
		}
		return false;
	}

	function formatRoleLabel(role: string): string {
		if (role === 'carousel') return 'Classification Channel';
		if (role === 'c_channel_2') return 'C-Channel 2';
		if (role === 'c_channel_3') return 'C-Channel 3';
		return role.replace('c_channel_', 'C-Channel ');
	}

	function channelViewBox(seg: Segment): string {
		const cx = seg.channel_center_x ?? seg.snapshot_width / 2;
		const cy = seg.channel_center_y ?? seg.snapshot_height / 2;
		const r =
			(seg.channel_radius_outer ?? Math.min(seg.snapshot_width, seg.snapshot_height) / 3) + 12;
		return `${cx - r} ${cy - r} ${r * 2} ${r * 2}`;
	}

	function wedgePath(
		cx: number,
		cy: number,
		rIn: number,
		rOut: number,
		a0Deg: number,
		a1Deg: number
	): string {
		const a0 = (a0Deg * Math.PI) / 180;
		const a1 = (a1Deg * Math.PI) / 180;
		const x0o = cx + rOut * Math.cos(a0);
		const y0o = cy + rOut * Math.sin(a0);
		const x1o = cx + rOut * Math.cos(a1);
		const y1o = cy + rOut * Math.sin(a1);
		const x0i = cx + rIn * Math.cos(a0);
		const y0i = cy + rIn * Math.sin(a0);
		const x1i = cx + rIn * Math.cos(a1);
		const y1i = cy + rIn * Math.sin(a1);
		const largeArc = Math.abs(a1 - a0) > Math.PI ? 1 : 0;
		return `M ${x0i} ${y0i} L ${x0o} ${y0o} A ${rOut} ${rOut} 0 ${largeArc} 1 ${x1o} ${y1o} L ${x1i} ${y1i} A ${rIn} ${rIn} 0 ${largeArc} 0 ${x0i} ${y0i} Z`;
	}

	function hasSectorGeom(seg: Segment): boolean {
		return (
			seg.channel_center_x != null &&
			seg.channel_center_y != null &&
			seg.channel_radius_inner != null &&
			seg.channel_radius_outer != null &&
			(seg.sector_snapshots?.length ?? 0) > 0
		);
	}

	function pathPolylinePoints(seg: Segment): string {
		return seg.path.map((p) => `${p[1]},${p[2]}`).join(' ');
	}

	function nearestPathPoint(path: PathPoint[], ts: number): PathPoint | null {
		if (!path || path.length === 0) return null;
		let best = path[0];
		let bestDiff = Math.abs(path[0][0] - ts);
		for (let i = 1; i < path.length; i++) {
			const d = Math.abs(path[i][0] - ts);
			if (d < bestDiff) {
				bestDiff = d;
				best = path[i];
			}
		}
		return best;
	}

	// Signature of the current detail: "live|seg0_snaps,seg1_snaps,...". When
	// a poll returns the same signature we keep the existing `detail` object
	// so Svelte doesn't re-diff the SVG (which would reload every <image>
	// href even though the b64 payload hasn't changed).
	function detailSignature(d: Detail | null): string {
		if (!d) return '';
		const counts = d.segments.map((s) => s.sector_snapshots?.length ?? 0).join(',');
		return `${d.live ? 1 : 0}|${counts}`;
	}

	async function load() {
		if (!Number.isFinite(globalId)) return;
		loading = true;
		try {
			const res = await fetch(`${effectiveBase()}/api/feeder/tracking/history/${globalId}`);
			if (!res.ok) {
				error = res.status === 404 ? 'Track not found' : `HTTP ${res.status}`;
				return;
			}
			const next = (await res.json()) as Detail;
			if (detailSignature(next) !== detailSignature(detail)) {
				detail = next;
			} else if (detail && next.live !== detail.live) {
				// Snapshot count unchanged but live flag flipped — update in place
				// without replacing the object so the SVG doesn't re-mount.
				detail.live = next.live;
			}
			error = null;
		} catch (e: any) {
			error = e?.message ?? 'Failed to load';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void load();
		// LIVE tracks keep extending while the piece is still moving — poll
		// until the backend flips detail.live to false.
		pollTimer = setInterval(() => {
			if (detail?.live) void load();
		}, 1500);
	});

	onDestroy(() => {
		if (pollTimer !== null) clearInterval(pollTimer);
	});
</script>

{#if error}
	<div class="border border-danger bg-danger/10 p-3 text-sm text-danger">{error}</div>
{:else if !detail}
	<div class="text-sm text-text-muted">{loading ? 'Loading track…' : 'No track data.'}</div>
{:else}
	<div class="flex flex-col gap-3">
		{#each detail.segments as segment, idx (idx)}
			<div class="border border-border bg-bg">
				<div class="flex items-center justify-between border-b border-border bg-surface px-3 py-2 text-sm">
					<span class="font-medium text-text">
						{formatRoleLabel(segment.source_role)}
						{#if segment.handoff_from}
							<span class="ml-2 text-primary">
								← handoff from {formatRoleLabel(segment.handoff_from)}
							</span>
						{/if}
					</span>
					<span class="text-text-muted">
						{segment.hit_count} frames · {segment.duration_s.toFixed(2)}s
						{#if segment.sector_snapshots && segment.sector_snapshots.length > 0}
							· {segment.sector_snapshots.length}/{segment.sector_count ?? 0} sectors
						{/if}
					</span>
				</div>
				{#if hasSectorGeom(segment)}
					<svg
						viewBox={channelViewBox(segment)}
						class="block h-auto w-full"
						preserveAspectRatio="xMidYMid meet"
					>
						<defs>
							{#each segment.sector_snapshots as s (s.captured_ts)}
								<clipPath id={`detail-sec-${globalId}-${idx}-${s.captured_ts}`}>
									<path
										d={wedgePath(
											segment.channel_center_x as number,
											segment.channel_center_y as number,
											s.r_inner && s.r_inner > 0
												? s.r_inner
												: (segment.channel_radius_inner as number),
											s.r_outer && s.r_outer > 0
												? s.r_outer
												: (segment.channel_radius_outer as number),
											s.start_angle_deg,
											s.end_angle_deg
										)}
									/>
								</clipPath>
							{/each}
						</defs>
						<image
							href={`data:image/jpeg;base64,${segment.snapshot_jpeg_b64}`}
							x="0"
							y="0"
							width={segment.snapshot_width}
							height={segment.snapshot_height}
							opacity="0.22"
						/>
						{#each segment.sector_snapshots as s (s.captured_ts)}
							<image
								href={`data:image/jpeg;base64,${s.jpeg_b64}`}
								x={s.bbox_x}
								y={s.bbox_y}
								width={s.width}
								height={s.height}
								clip-path={`url(#detail-sec-${globalId}-${idx}-${s.captured_ts})`}
							/>
						{/each}
						<circle
							cx={segment.channel_center_x as number}
							cy={segment.channel_center_y as number}
							r={segment.channel_radius_outer as number}
							fill="none"
							stroke="rgba(255,255,255,0.35)"
							stroke-width="2"
						/>
						<circle
							cx={segment.channel_center_x as number}
							cy={segment.channel_center_y as number}
							r={segment.channel_radius_inner as number}
							fill="none"
							stroke="rgba(255,255,255,0.35)"
							stroke-width="2"
						/>
						{#if segment.path.length > 1}
							<polyline
								points={pathPolylinePoints(segment)}
								fill="none"
								stroke={segment.handoff_from ? 'rgba(220,80,220,0.9)' : 'rgba(0,220,0,0.9)'}
								stroke-width="3"
								stroke-linejoin="round"
							/>
						{/if}
						{#each segment.sector_snapshots as s (s.captured_ts)}
							{@const hit = nearestPathPoint(segment.path, s.captured_ts)}
							{#if hit}
								{@const used = isUsedCrop(s.captured_ts)}
								<circle
									cx={hit[1]}
									cy={hit[2]}
									r={used ? 40 : 28}
									fill="none"
									stroke={used ? 'var(--color-primary, #D01012)' : 'rgba(255,220,0,0.75)'}
									stroke-width={used ? 5 : 2}
								/>
							{/if}
						{/each}
					</svg>
				{:else}
					<div class="p-3 text-sm text-text-muted">Segment has no sector geometry yet.</div>
				{/if}
			</div>
		{/each}
	</div>
{/if}

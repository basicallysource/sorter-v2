<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { X } from 'lucide-svelte';

	type PathPoint = [number, number, number]; // ts, x, y

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
		piece_bbox_x?: number;
		piece_bbox_y?: number;
		piece_width?: number;
		piece_height?: number;
	};

	function pieceJpeg(s: SectorSnapshot): string {
		return s.piece_jpeg_b64 && s.piece_jpeg_b64.length > 0 ? s.piece_jpeg_b64 : s.jpeg_b64;
	}

	function channelViewBox(seg: Segment): string {
		// Crop the big view tight around the annular channel so half the
		// image isn't empty backdrop. Adds a small padding beyond r_outer.
		const cx = seg.channel_center_x ?? seg.snapshot_width / 2;
		const cy = seg.channel_center_y ?? seg.snapshot_height / 2;
		const r = (seg.channel_radius_outer ?? Math.min(seg.snapshot_width, seg.snapshot_height) / 3) + 12;
		return `${cx - r} ${cy - r} ${r * 2} ${r * 2}`;
	}

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

	function wedgePath(cx: number, cy: number, rIn: number, rOut: number, a0Deg: number, a1Deg: number): string {
		const deltaDeg = ((((a1Deg - a0Deg) % 360) + 360) % 360) || 360;
		const endDeg = a0Deg + deltaDeg;
		const a0 = (a0Deg * Math.PI) / 180;
		const a1 = (endDeg * Math.PI) / 180;
		const x0o = cx + rOut * Math.cos(a0);
		const y0o = cy + rOut * Math.sin(a0);
		const x1o = cx + rOut * Math.cos(a1);
		const y1o = cy + rOut * Math.sin(a1);
		const x0i = cx + rIn * Math.cos(a0);
		const y0i = cy + rIn * Math.sin(a0);
		const x1i = cx + rIn * Math.cos(a1);
		const y1i = cy + rIn * Math.sin(a1);
		const largeArc = deltaDeg > 180 ? 1 : 0;
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

	function sectorSnapshots(seg: Segment): SectorSnapshot[] {
		return seg.sector_snapshots ?? [];
	}

	type RecognizeResult = {
		best_item?: { id: string; name: string; score: number; img_url?: string } | null;
		best_color?: { id: string; name: string } | null;
		error?: string;
		loading?: boolean;
	};

	// Keyed by the crop's stable signature so repeat clicks don't reshuffle.
	let recognizeResults = $state<Record<string, RecognizeResult>>({});
	// Per-segment combined-multi-crop result. Keyed by segment idx.
	let recognizeAllResults = $state<Record<number, RecognizeResult>>({});

	async function recognizeCrop(key: string, jpegB64: string) {
		recognizeResults = { ...recognizeResults, [key]: { loading: true } };
		try {
			const res = await fetch(`${effectiveBase()}/api/feeder/tracking/recognize`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ jpeg_b64: jpegB64 })
			});
			if (!res.ok) {
				const text = await res.text();
				recognizeResults = {
					...recognizeResults,
					[key]: { error: text.slice(0, 200) }
				};
				return;
			}
			const data = await res.json();
			recognizeResults = {
				...recognizeResults,
				[key]: { best_item: data.best_item ?? null, best_color: data.best_color ?? null }
			};
		} catch (e: any) {
			recognizeResults = {
				...recognizeResults,
				[key]: { error: e?.message ?? 'failed' }
			};
		}
	}

	async function recognizeAll(segmentIdx: number, jpegs: string[]) {
		if (jpegs.length === 0) return;
		recognizeAllResults = { ...recognizeAllResults, [segmentIdx]: { loading: true } };
		try {
			const res = await fetch(`${effectiveBase()}/api/feeder/tracking/recognize`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ jpegs_b64: jpegs })
			});
			if (!res.ok) {
				const text = await res.text();
				recognizeAllResults = {
					...recognizeAllResults,
					[segmentIdx]: { error: text.slice(0, 200) }
				};
				return;
			}
			const data = await res.json();
			recognizeAllResults = {
				...recognizeAllResults,
				[segmentIdx]: { best_item: data.best_item ?? null, best_color: data.best_color ?? null }
			};
		} catch (e: any) {
			recognizeAllResults = {
				...recognizeAllResults,
				[segmentIdx]: { error: e?.message ?? 'failed' }
			};
		}
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

	function pathPolylinePoints(seg: Segment): string {
		return seg.path.map((p) => `${p[1]},${p[2]}`).join(' ');
	}

	type BurstFrame = {
		frame_index: number;
		timestamp: number;
		phase: 'pre' | 'post';
		detected: boolean;
		jpeg_b64: string;
		crop_jpeg_b64: string;
		bbox: [number, number, number, number] | null;
		score: number | null;
	};

	type Detail = {
		global_id: number;
		created_at: number;
		finished_at: number;
		duration_s: number;
		roles: string[];
		handoff_count: number;
		segment_count: number;
		total_hit_count: number;
		segments: Segment[];
		drop_zone_burst?: BurstFrame[];
		live?: boolean;
	};

	let { globalId, onClose }: { globalId: number; onClose: () => void } = $props();

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	let detail = $state<Detail | null>(null);
	let error = $state<string | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	async function load() {
		try {
			const res = await fetch(`${effectiveBase()}/api/feeder/tracking/history/${globalId}`);
			if (!res.ok) {
				error = res.status === 404 ? 'Track not found' : `HTTP ${res.status}`;
				return;
			}
			detail = await res.json();
			error = null;
		} catch (e: any) {
			error = e?.message ?? 'Failed to load';
		}
	}

	function formatHashId(id: number): string {
		const mixed = (id * 2654435761) >>> 0;
		return (mixed % 10000).toString().padStart(4, '0');
	}

	function handleKey(event: KeyboardEvent) {
		if (event.key === 'Escape') onClose();
	}

	function drawSegment(canvas: HTMLCanvasElement, segment: Segment) {
		const ctx2d = canvas.getContext('2d');
		if (!ctx2d) return;
		const img = new Image();
		img.onload = () => {
			canvas.width = segment.snapshot_width;
			canvas.height = segment.snapshot_height;
			ctx2d.drawImage(img, 0, 0);
			if (segment.path.length > 1) {
				ctx2d.strokeStyle = segment.handoff_from ? 'rgba(220, 80, 220, 0.9)' : 'rgba(0, 220, 0, 0.9)';
				ctx2d.lineWidth = 3;
				ctx2d.lineJoin = 'round';
				ctx2d.beginPath();
				ctx2d.moveTo(segment.path[0][1], segment.path[0][2]);
				for (let i = 1; i < segment.path.length; i++) {
					ctx2d.lineTo(segment.path[i][1], segment.path[i][2]);
				}
				ctx2d.stroke();
				// Start marker
				const [, sx, sy] = segment.path[0];
				ctx2d.fillStyle = 'rgba(255, 255, 255, 0.95)';
				ctx2d.beginPath();
				ctx2d.arc(sx, sy, 7, 0, Math.PI * 2);
				ctx2d.fill();
				ctx2d.strokeStyle = 'rgba(0, 0, 0, 0.9)';
				ctx2d.lineWidth = 2;
				ctx2d.stroke();
				// End marker
				const [, ex, ey] = segment.path[segment.path.length - 1];
				ctx2d.fillStyle = segment.handoff_from ? 'rgba(220, 80, 220, 0.95)' : 'rgba(0, 220, 0, 0.95)';
				ctx2d.beginPath();
				ctx2d.arc(ex, ey, 7, 0, Math.PI * 2);
				ctx2d.fill();
				ctx2d.strokeStyle = 'rgba(0, 0, 0, 0.9)';
				ctx2d.lineWidth = 2;
				ctx2d.stroke();
			}
		};
		img.src = `data:image/jpeg;base64,${segment.snapshot_jpeg_b64}`;
	}

	$effect(() => {
		if (!detail) return;
		// Draw after DOM updates.
		queueMicrotask(() => {
			detail?.segments.forEach((segment, idx) => {
				const canvas = document.querySelector(
					`[data-segment-canvas="${globalId}-${idx}"]`
				) as HTMLCanvasElement | null;
				if (canvas) drawSegment(canvas, segment);
			});
		});
	});

	onMount(() => {
		void load();
		// Live tracks: keep polling so the path extends while the piece is still moving.
		pollTimer = setInterval(() => void load(), 1500);
	});

	onDestroy(() => {
		if (pollTimer !== null) clearInterval(pollTimer);
	});
</script>

<svelte:window onkeydown={handleKey} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
	class="fixed inset-0 z-50 flex items-stretch justify-stretch bg-black/90"
	onclick={onClose}
	role="dialog"
	aria-modal="true"
	aria-label="Tracked piece detail"
	tabindex="-1"
>
	<div
		class="relative flex h-screen w-screen flex-col overflow-y-auto bg-surface"
		onclick={(e) => e.stopPropagation()}
	>
		<div class="flex items-center justify-between border-b border-border bg-bg px-4 py-3">
			<div class="flex items-center gap-3">
				<span class="font-mono text-lg font-semibold text-text">
					#{formatHashId(globalId)}
				</span>
				{#if detail}
					<span class="text-xs text-text-muted">
						{detail.roles.map((r) => r.replace('c_channel_', 'C')).join(' → ')}
						· {detail.total_hit_count} frames
						· {detail.duration_s.toFixed(2)}s
						{#if detail.live}
							<span class="ml-2 border border-success px-1 text-success">LIVE</span>
						{/if}
						{#if detail.handoff_count > 0}
							<span class="ml-2 border border-primary px-1 text-primary">
								{detail.handoff_count} handoff{detail.handoff_count === 1 ? '' : 's'}
							</span>
						{/if}
					</span>
				{/if}
			</div>
			<button
				type="button"
				onclick={onClose}
				aria-label="Close"
				class="p-1 text-text-muted hover:text-text"
			>
				<X size={18} />
			</button>
		</div>

		<div class="p-4">
			{#if error}
				<div class="border border-danger bg-danger/10 p-3 text-sm text-danger">{error}</div>
			{:else if !detail}
				<div class="text-sm text-text-muted">Loading…</div>
			{:else}
				<div class="flex flex-col gap-4">
					{#if detail.drop_zone_burst && detail.drop_zone_burst.length > 0}
						{@const burstFrames = detail.drop_zone_burst}
						{@const detectedCount = burstFrames.filter((f) => f.detected).length}
						<div class="border border-border">
							<div class="flex items-center justify-between bg-bg px-3 py-1.5 text-xs">
								<span class="font-medium text-text">Drop-zone burst</span>
								<span class="text-text-muted">
									{burstFrames.length} frames · {detectedCount} detections · ±2s around C4 entry
								</span>
							</div>
							<div class="p-3">
								<div class="grid grid-cols-6 gap-1 sm:grid-cols-10">
									{#each burstFrames as frame, fIdx (fIdx)}
										<div
											class="relative border {frame.phase === 'pre'
												? 'border-border'
												: 'border-primary/40'} bg-bg"
											title="Frame {frame.frame_index} · {frame.phase} · {frame.detected ? 'detected' : 'no detection'}{frame.score != null ? ' · ' + (frame.score * 100).toFixed(0) + '%' : ''}"
										>
											<img
												src={`data:image/jpeg;base64,${frame.detected && frame.crop_jpeg_b64 ? frame.crop_jpeg_b64 : frame.jpeg_b64}`}
												alt=""
												class="block h-auto w-full object-contain"
												loading="lazy"
											/>
											{#if !frame.detected}
												<div class="absolute inset-0 bg-black/40"></div>
											{/if}
											<div class="absolute bottom-0 left-0 right-0 bg-black/60 px-0.5 text-center text-xs leading-tight">
												<span class={frame.phase === 'pre' ? 'text-text-muted' : 'text-primary'}>
													{frame.phase === 'pre' ? 'pre' : 'post'}
												</span>
											</div>
										</div>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					{#each detail.segments as segment, idx (idx)}
						<div class="border border-border">
							<div class="flex items-center justify-between bg-bg px-3 py-1.5 text-xs">
								<span class="font-medium text-text">
									{segment.source_role.replace('c_channel_', 'C-Channel ')}
									{#if segment.handoff_from}
										<span class="ml-2 text-primary">← handoff from {segment.handoff_from.replace('c_channel_', 'C-Channel ')}</span>
									{/if}
								</span>
								<span class="text-text-muted">
									{segment.hit_count} frames · {segment.path_points} path points · {segment.duration_s.toFixed(2)}s
									{#if sectorSnapshots(segment).length > 0}
										· {sectorSnapshots(segment).length}/{segment.sector_count ?? 0} sectors
									{/if}
								</span>
							</div>
							<div class="flex min-h-0 flex-col lg:flex-row">
							<div class="relative flex-1 bg-bg">
								{#if hasSectorGeom(segment)}
									<svg
										viewBox={channelViewBox(segment)}
										class="block h-auto w-full"
										preserveAspectRatio="xMidYMid meet"
									>
										<defs>
											{#each sectorSnapshots(segment) as s, sIdx (sIdx)}
												<clipPath id={`sec-${globalId}-${idx}-${sIdx}`}>
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
										{#each sectorSnapshots(segment) as s, sIdx (sIdx)}
											<image
												href={`data:image/jpeg;base64,${s.jpeg_b64}`}
												x={s.bbox_x}
												y={s.bbox_y}
												width={s.width}
												height={s.height}
												clip-path={`url(#sec-${globalId}-${idx}-${sIdx})`}
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
										{#each sectorSnapshots(segment) as s, sIdx (sIdx)}
											{@const hit = nearestPathPoint(segment.path, s.captured_ts)}
											{#if hit}
												<circle
													cx={hit[1]}
													cy={hit[2]}
													r="32"
													fill="none"
													stroke="rgba(255,220,0,0.95)"
													stroke-width="3"
												/>
											{/if}
										{/each}
									</svg>
								{:else}
									<canvas
										data-segment-canvas={`${globalId}-${idx}`}
										class="block h-auto w-full"
									></canvas>
								{/if}
							</div>
							{#if sectorSnapshots(segment).length > 0}
								{@const allJpegs = sectorSnapshots(segment).map((s) => pieceJpeg(s))}
								{@const allRecog = recognizeAllResults[idx]}
								<aside class="flex w-full flex-col border-t border-border bg-bg/50 lg:w-[320px] lg:border-t-0 lg:border-l">
									<div class="flex flex-col gap-2 border-b border-border px-3 py-2">
										<div class="flex items-center justify-between gap-2">
											<span class="text-sm font-medium uppercase tracking-wider text-text-muted">
												Object crops · {sectorSnapshots(segment).length}
											</span>
											<button
												type="button"
												onclick={() => void recognizeAll(idx, allJpegs)}
												disabled={allRecog?.loading}
												class="border border-primary/50 bg-primary/10 px-2 py-1 text-sm font-medium text-primary hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-50"
											>
												{allRecog?.loading ? 'Recognizing…' : 'Recognize all'}
											</button>
										</div>
										{#if allRecog && !allRecog.loading}
											<div class="flex flex-col gap-2 border border-border bg-surface p-2 text-sm">
												{#if allRecog.error}
													<span class="text-danger" title={allRecog.error}>failed</span>
												{:else if allRecog.best_item}
													{#if allRecog.best_item.img_url}
														<img
															src={allRecog.best_item.img_url}
															alt="Combined Brickognize reference"
															class="block h-auto w-full border border-border bg-white object-contain"
															loading="lazy"
														/>
													{/if}
													<div class="flex flex-col gap-0.5">
														<span class="font-mono font-medium text-text">
															{allRecog.best_item.id} · {(allRecog.best_item.score * 100).toFixed(0)}%
														</span>
														<span class="text-text-muted" title={allRecog.best_item.name}>
															{allRecog.best_item.name}
														</span>
														{#if allRecog.best_color}
															<span class="text-text-muted">{allRecog.best_color.name}</span>
														{/if}
														<span class="text-xs text-text-muted">
															Combined from all {sectorSnapshots(segment).length} crops
														</span>
													</div>
												{:else}
													<span class="text-text-muted">no match</span>
												{/if}
											</div>
										{/if}
									</div>
									<div class="flex flex-col gap-3 overflow-y-auto p-3" style="max-height: calc(100vh - 12rem);">
										{#each sectorSnapshots(segment) as s, sIdx (sIdx)}
											{@const cropKey = `${globalId}-${idx}-${sIdx}-${s.captured_ts}`}
											{@const recog = recognizeResults[cropKey]}
											{@const pieceB64 = pieceJpeg(s)}
											<div class="flex flex-col border border-border bg-surface">
												<div class="bg-bg">
													<img
														src={`data:image/jpeg;base64,${pieceB64}`}
														alt=""
														class="block h-auto w-full object-contain"
													/>
												</div>
												<div class="flex items-center justify-between gap-2 px-2 py-1.5">
													<span class="text-sm text-text-muted">
														{Math.round(s.start_angle_deg)}°–{Math.round(s.end_angle_deg)}°
													</span>
													<button
														type="button"
														onclick={() => void recognizeCrop(cropKey, pieceB64)}
														disabled={recog?.loading}
														class="border border-primary/50 bg-primary/10 px-2 py-0.5 text-sm font-medium text-primary hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-50"
													>
														{recog?.loading ? '…' : 'Recognize'}
													</button>
												</div>
												{#if recog && !recog.loading}
													<div class="flex flex-col gap-1.5 border-t border-border px-2 py-2 text-sm">
														{#if recog.error}
															<span class="text-danger" title={recog.error}>failed</span>
														{:else if recog.best_item}
															{#if recog.best_item.img_url}
																<img
																	src={recog.best_item.img_url}
																	alt="Brickognize reference"
																	class="block h-auto w-full border border-border bg-white object-contain"
																	loading="lazy"
																/>
															{/if}
															<div class="flex flex-col gap-0.5">
																<span class="font-mono font-medium text-text">
																	{recog.best_item.id} · {(recog.best_item.score * 100).toFixed(0)}%
																</span>
																<span class="text-text-muted" title={recog.best_item.name}>
																	{recog.best_item.name}
																</span>
																{#if recog.best_color}
																	<span class="text-text-muted">{recog.best_color.name}</span>
																{/if}
															</div>
														{:else}
															<span class="text-text-muted">no match</span>
														{/if}
													</div>
												{/if}
											</div>
										{/each}
									</div>
								</aside>
							{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>
</div>

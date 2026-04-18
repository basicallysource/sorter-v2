<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import { ArrowLeft, RefreshCw } from 'lucide-svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { getMachineContext } from '$lib/machines/context';

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
		piece_bbox_x?: number;
		piece_bbox_y?: number;
		piece_width?: number;
		piece_height?: number;
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
		auto_recognition?: AutoRecognition | null;
	};

	type AutoRecognition = {
		status: 'pending' | 'ok' | 'insufficient_consistency' | 'insufficient_quality' | 'error';
		image_count?: number;
		total_crops?: number;
		inlier_count?: number;
		queued_count?: number;
		kept_count?: number;
		rejected_for_quality?: number;
		error?: string;
		best_item?: { id: string; name: string; score: number; img_url?: string } | null;
		best_color?: { id: string; name: string } | null;
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
		live?: boolean;
	};

	type RecognizeResult = {
		best_item?: { id: string; name: string; score: number; img_url?: string } | null;
		best_color?: { id: string; name: string } | null;
		error?: string;
		loading?: boolean;
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	let globalId = $derived(Number(page.params.globalId));
	let detail = $state<Detail | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(false);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	let recognizeResults = $state<Record<string, RecognizeResult>>({});
	let recognizeAllResults = $state<Record<number, RecognizeResult>>({});

	function pieceJpeg(s: SectorSnapshot): string {
		return s.piece_jpeg_b64 && s.piece_jpeg_b64.length > 0 ? s.piece_jpeg_b64 : s.jpeg_b64;
	}

	function channelViewBox(seg: Segment): string {
		const cx = seg.channel_center_x ?? seg.snapshot_width / 2;
		const cy = seg.channel_center_y ?? seg.snapshot_height / 2;
		const r = (seg.channel_radius_outer ?? Math.min(seg.snapshot_width, seg.snapshot_height) / 3) + 12;
		return `${cx - r} ${cy - r} ${r * 2} ${r * 2}`;
	}

	function wedgePath(cx: number, cy: number, rIn: number, rOut: number, a0Deg: number, a1Deg: number): string {
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

	function sectorSnapshots(seg: Segment): SectorSnapshot[] {
		return seg.sector_snapshots ?? [];
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

	function formatHashId(id: number): string {
		const mixed = (id * 2654435761) >>> 0;
		return (mixed % 10000).toString().padStart(4, '0');
	}

	async function load() {
		loading = true;
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
		} finally {
			loading = false;
		}
	}

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
				recognizeResults = { ...recognizeResults, [key]: { error: text.slice(0, 200) } };
				return;
			}
			const data = await res.json();
			recognizeResults = {
				...recognizeResults,
				[key]: { best_item: data.best_item ?? null, best_color: data.best_color ?? null }
			};
		} catch (e: any) {
			recognizeResults = { ...recognizeResults, [key]: { error: e?.message ?? 'failed' } };
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

	onMount(() => {
		void load();
		// For LIVE tracks the path keeps extending — poll while that's the
		// case, but stop as soon as detail.live becomes false.
		pollTimer = setInterval(() => {
			if (detail?.live) void load();
		}, 1500);
	});

	onDestroy(() => {
		if (pollTimer !== null) clearInterval(pollTimer);
	});
</script>

<svelte:head>
	<title>Track #{globalId} · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="flex flex-col gap-4 p-4 sm:p-6">
		<header class="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
			<div class="flex items-center gap-3">
				<a
					href="/tracked"
					class="inline-flex items-center gap-1.5 border border-border bg-surface px-2.5 py-1.5 text-sm text-text-muted hover:text-text"
				>
					<ArrowLeft size={14} />
					Back
				</a>
				<span class="font-mono text-lg font-semibold text-text">
					#{formatHashId(globalId)}
				</span>
				{#if detail}
					<span class="text-sm text-text-muted">
						{detail.roles.map((r) => r.replace('c_channel_', 'C')).join(' → ')}
						· {detail.total_hit_count} frames
						· {detail.duration_s.toFixed(2)}s
					</span>
					{#if detail.live}
						<span class="border border-success px-1.5 text-sm text-success">LIVE</span>
					{/if}
					{#if detail.handoff_count > 0}
						<span class="border border-primary px-1.5 text-sm text-primary">
							{detail.handoff_count} handoff{detail.handoff_count === 1 ? '' : 's'}
						</span>
					{/if}
				{/if}
			</div>
			<button
				type="button"
				onclick={() => void load()}
				disabled={loading}
				aria-label="Reload"
				title="Reload"
				class="border border-border bg-surface p-1.5 text-text-muted hover:text-text disabled:opacity-50"
			>
				<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
			</button>
		</header>

		{#if error}
			<div class="border border-danger bg-danger/10 p-3 text-sm text-danger">{error}</div>
		{:else if !detail}
			<div class="text-sm text-text-muted">Loading…</div>
		{:else}
			<div class="flex flex-col gap-4">
				{#each detail.segments as segment, idx (idx)}
					<div class="border border-border bg-surface">
						{#if segment.auto_recognition}
							{@const auto = segment.auto_recognition}
							<div class="flex items-start gap-3 border-b border-border bg-bg px-3 py-2">
								{#if auto.status === 'ok' && auto.best_item}
									{#if auto.best_item.img_url}
										<img
											src={auto.best_item.img_url}
											alt="Brickognize auto result"
											class="h-16 w-16 flex-shrink-0 border border-border bg-white object-contain"
											loading="lazy"
										/>
									{/if}
									<div class="flex min-w-0 flex-1 flex-col gap-0.5 text-sm">
										<span class="text-xs font-medium uppercase tracking-wider text-text-muted">
											Auto-recognized from {auto.image_count} crops
										</span>
										<span class="font-mono text-base font-semibold text-text">
											{auto.best_item.id} · {(auto.best_item.score * 100).toFixed(0)}%
										</span>
										<span class="text-text-muted" title={auto.best_item.name}>
											{auto.best_item.name}
										</span>
										{#if auto.best_color}
											<span class="text-text-muted">{auto.best_color.name}</span>
										{/if}
									</div>
								{:else if auto.status === 'pending'}
									<span class="text-sm text-text-muted">
										Auto-recognize pending ({auto.queued_count ?? ''} crops in queue)…
									</span>
								{:else if auto.status === 'insufficient_consistency'}
									<span class="text-sm text-warning-dark" title="Crops didn't cluster around one piece">
										Auto-recognize skipped: mixed crops ({auto.inlier_count}/{auto.total_crops})
									</span>
								{:else if auto.status === 'insufficient_quality'}
									<span class="text-sm text-warning-dark" title="Too many crops were blurry / overexposed">
										Auto-recognize skipped: low quality ({auto.kept_count}/{auto.total_crops})
									</span>
								{:else if auto.status === 'error'}
									<span class="text-sm text-danger" title={auto.error}>
										Auto-recognize failed
									</span>
								{/if}
							</div>
						{/if}
						<div class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm">
							<span class="font-medium text-text">
								{segment.source_role.replace('c_channel_', 'C-Channel ')}
								{#if segment.handoff_from}
									<span class="ml-2 text-primary">
										← handoff from {segment.handoff_from.replace('c_channel_', 'C-Channel ')}
									</span>
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
								{/if}
							</div>

							{#if sectorSnapshots(segment).length > 0}
								{@const allJpegs = sectorSnapshots(segment).map((s) => pieceJpeg(s))}
								{@const allRecog = recognizeAllResults[idx]}
								<aside class="flex w-full flex-col border-t border-border bg-bg/50 lg:w-[360px] lg:border-t-0 lg:border-l">
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
													<div class="flex flex-col gap-1 text-danger">
														<span class="font-medium">Recognize failed</span>
														<span class="break-words text-xs text-danger/80">{allRecog.error}</span>
													</div>
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
									<div class="flex flex-col gap-3 p-3">
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
															<div class="flex flex-col gap-0.5 text-danger">
																<span class="font-medium">Recognize failed</span>
																<span class="break-words text-xs text-danger/80">{recog.error}</span>
															</div>
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

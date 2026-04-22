<script lang="ts">
	// ShadowOverlay — renders the rt/ shadow-mode tracks for a role as a
	// dashed magenta SVG overlay, plus a small "rt IoU (10s)" readout under
	// the preview. Additive: sits alongside the existing CameraFeed without
	// touching its own overlay logic.
	//
	// Polls /api/rt/shadow/tracks/<role> every ~500ms while `enabled` is
	// true; goes silent when disabled. /api/rt/shadow/status is hit at the
	// same cadence to keep the IoU readout fresh.
	import { onDestroy } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';

	type ShadowTrack = {
		track_id: number;
		global_id: number | null;
		piece_uuid: string | null;
		bbox_xyxy: [number, number, number, number];
		score: number;
		confirmed_real: boolean;
		hit_count: number;
		first_seen_ts: number;
		last_seen_ts: number;
	};

	type TracksResponse = {
		role: string;
		available: boolean;
		feed_id: string | null;
		frame_seq: number | null;
		timestamp: number | null;
		tracks: ShadowTrack[];
		lost_track_ids: number[];
		iou: { mean_iou: number; sample_count: number; window_sec: number };
	};

	type StatusResponse = {
		enabled: boolean;
		roles: Array<{
			role: string;
			iou: { mean_iou: number; sample_count: number; window_sec: number };
		}>;
	};

	const POLL_MS = 500;

	let {
		role = 'c2',
		enabled = false,
		sourceWidth = 1920,
		sourceHeight = 1080
	}: {
		role?: string;
		enabled?: boolean;
		sourceWidth?: number;
		sourceHeight?: number;
	} = $props();

	const ctx = getMachineContext();

	function baseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	let tracks = $state<ShadowTrack[]>([]);
	let iouMean = $state<number | null>(null);
	let iouSamples = $state<number>(0);
	let iouWindow = $state<number>(0);
	let shadowAvailable = $state<boolean>(false);
	let lastError = $state<string | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	async function fetchOnce(): Promise<void> {
		if (!enabled) return;
		try {
			const [tracksRes, statusRes] = await Promise.all([
				fetch(`${baseUrl()}/api/rt/shadow/tracks/${encodeURIComponent(role)}`),
				fetch(`${baseUrl()}/api/rt/shadow/status`)
			]);
			if (tracksRes.ok) {
				const payload = (await tracksRes.json()) as TracksResponse;
				tracks = Array.isArray(payload.tracks) ? payload.tracks : [];
				shadowAvailable = Boolean(payload.available);
				if (payload.iou) {
					iouMean = Number(payload.iou.mean_iou);
					iouSamples = Number(payload.iou.sample_count ?? 0);
					iouWindow = Number(payload.iou.window_sec ?? 0);
				}
			} else {
				tracks = [];
				shadowAvailable = false;
			}
			if (statusRes.ok) {
				const status = (await statusRes.json()) as StatusResponse;
				const entry = status.roles?.find((r) => r.role === role);
				if (entry) {
					iouMean = Number(entry.iou.mean_iou);
					iouSamples = Number(entry.iou.sample_count ?? 0);
					iouWindow = Number(entry.iou.window_sec ?? 0);
				}
			}
			lastError = null;
		} catch (err) {
			lastError = err instanceof Error ? err.message : String(err);
		}
	}

	function startPolling(): void {
		if (pollTimer !== null) return;
		void fetchOnce();
		pollTimer = setInterval(() => {
			void fetchOnce();
		}, POLL_MS);
	}

	function stopPolling(): void {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
		tracks = [];
	}

	$effect(() => {
		if (enabled) {
			startPolling();
		} else {
			stopPolling();
		}
	});

	onDestroy(() => {
		stopPolling();
	});

	const iouText = $derived.by(() => {
		if (iouMean === null) return '—';
		return iouMean.toFixed(2);
	});
</script>

{#if enabled}
	<svg
		viewBox="0 0 {sourceWidth} {sourceHeight}"
		preserveAspectRatio="xMidYMid meet"
		class="pointer-events-none absolute inset-0 h-full w-full"
		aria-hidden="true"
	>
		{#each tracks as track (track.track_id)}
			{@const [x1, y1, x2, y2] = track.bbox_xyxy}
			{@const w = Math.max(0, x2 - x1)}
			{@const h = Math.max(0, y2 - y1)}
			<rect
				x={x1}
				y={y1}
				width={w}
				height={h}
				fill="none"
				stroke="#ff2bd6"
				stroke-width={Math.max(2, Math.round(sourceWidth / 480))}
				stroke-dasharray={`${Math.max(8, Math.round(sourceWidth / 140))} ${Math.max(
					6,
					Math.round(sourceWidth / 180)
				)}`}
				vector-effect="non-scaling-stroke"
			/>
		{/each}
	</svg>

	<div
		class="pointer-events-none absolute bottom-2 left-2 z-10 flex items-center gap-2 border border-white/20 bg-black/65 px-2 py-1 text-sm text-white/85 backdrop-blur-sm"
	>
		<span class="inline-block h-2 w-5" style="background: repeating-linear-gradient(90deg, #ff2bd6 0 4px, transparent 4px 7px);" aria-hidden="true"></span>
		<span class="font-semibold tracking-wide">rt shadow</span>
		<span class="text-white/70">
			{tracks.length} track{tracks.length === 1 ? '' : 's'}
		</span>
		<span class="text-white/60">
			· IoU ({iouWindow > 0 ? `${Math.round(iouWindow)}s` : '10s'}): {iouText}
		</span>
		{#if iouSamples > 0}
			<span class="text-white/45">· n={iouSamples}</span>
		{/if}
		{#if !shadowAvailable}
			<span class="text-warning">· disabled</span>
		{/if}
		{#if lastError}
			<span class="text-danger">· err</span>
		{/if}
	</div>
{/if}

<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { DashboardFeedCrop } from '$lib/dashboard/crops';
	import { acquireCameraWebrtcSession, type CameraWebrtcLease } from '$lib/camera/webrtc-session';
	import {
		decideCameraFeedMetadataUpdate,
		type CameraFeedMetadata as FeedMetadata,
		type CameraFeedMetadataViewport as FeedMetadataViewport
	} from '$lib/camera/metadata-sync';
	import {
		legacyMjpegFallbackAllowed,
		webrtcTransportCandidate
	} from '$lib/camera/transport-policy';
	import { cameraFeedRenderPolicy } from '$lib/camera/render-policy';
	import StreamControlsOverlay from '$lib/components/StreamControlsOverlay.svelte';
	import { WifiOff, Loader2, VideoOff } from 'lucide-svelte';
	import { onDestroy, onMount, untrack } from 'svelte';

	type ControlKey = 'annotations' | 'crop' | 'zones' | 'fullscreen';
	type Point = [number, number];
	type MediaViewport = {
		x: number;
		y: number;
		width: number;
		height: number;
	};
	type MediaLayout = {
		imageStyle: string;
		overlayStyle: string;
		viewBox: string;
	};
	type OverlayItem =
		| {
				kind: 'polygon';
				points: string;
				category: string;
				key: string;
		  }
		| {
				kind: 'bbox';
				x: number;
				y: number;
				width: number;
				height: number;
				label: string;
				key: string;
		  };

	let {
		camera,
		label = '',
		baseUrl = '',
		showHeader = true,
		framed = true,
		crop = null,
		showOverlay = false,
		defaultAnnotated = true,
		defaultCropped = undefined,
		defaultZones = true,
		controls = ['annotations'],
		direct = false,
		preferWebrtc = true,
		layer = $bindable('annotated')
	}: {
		camera: string;
		label?: string;
		baseUrl?: string;
		showHeader?: boolean;
		framed?: boolean;
		crop?: DashboardFeedCrop | null;
		showOverlay?: boolean;
		defaultAnnotated?: boolean;
		defaultCropped?: boolean;
		defaultZones?: boolean;
		controls?: ControlKey[];
		// Use the direct setup MJPEG path only as the legacy fallback. WebRTC is
		// still attempted first when the target transport is ready, so setup views
		// can share the same physical camera media track as the dashboard.
		direct?: boolean;
		preferWebrtc?: boolean;
		layer?: 'raw' | 'annotated';
	} = $props();

	const ctx = getMachineContext();

	function effectiveBaseUrl(): string {
		if (baseUrl) return baseUrl;
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	// Persistent per-camera toggle state — survives reloads via localStorage.
	// Keyed by camera so e.g. c_channel_2's crop toggle doesn't leak into
	// the carousel's. Falls back to the ``default*`` props when no saved
	// value exists.
	const storageKey = (key: string) => `camera-feed:${camera}:${key}`;

	function readPersisted(key: string, fallback: boolean): boolean {
		if (typeof localStorage === 'undefined') return fallback;
		try {
			const raw = localStorage.getItem(storageKey(key));
			if (raw === null) return fallback;
			return raw === '1' || raw === 'true';
		} catch {
			return fallback;
		}
	}

	function writePersisted(key: string, value: boolean) {
		if (typeof localStorage === 'undefined') return;
		try {
			localStorage.setItem(storageKey(key), value ? '1' : '0');
		} catch {
			// Quota / private mode — silently ignore.
		}
	}

	/* svelte-ignore state_referenced_locally */
	let annotated = $state(readPersisted('annotated', defaultAnnotated && layer === 'annotated'));
	// Legacy: presence of `crop` prop defaulted cropping on. Honor that unless
	// the caller explicitly sets `defaultCropped`.
	/* svelte-ignore state_referenced_locally */
	let cropped = $state(readPersisted('cropped', defaultCropped ?? crop !== null));
	/* svelte-ignore state_referenced_locally */
	let zones = $state(readPersisted('zones', defaultZones));

	// Keep legacy `layer` prop synced with new `annotated` state so existing
	// consumers (e.g. dashboard) binding to `layer` keep working.
	$effect(() => {
		layer = annotated ? 'annotated' : 'raw';
	});
	$effect(() => {
		annotated = layer === 'annotated';
	});

	// Write-back side: every toggle change writes to localStorage.
	$effect(() => {
		writePersisted('annotated', annotated);
	});
	$effect(() => {
		writePersisted('cropped', cropped);
	});
	$effect(() => {
		writePersisted('zones', zones);
	});

	const showAnnotations = $derived(controls.includes('annotations'));
	const showCrop = $derived(controls.includes('crop'));
	const showZones = $derived(controls.includes('zones'));
	const showFullscreen = $derived(controls.includes('fullscreen'));
	const effectiveZones = $derived(showZones ? zones : defaultZones);

	let fullscreenOpen = $state(false);
	let streamRetry = $state(0);
	let metadataRetry = $state(0);
	let feedMetadata = $state<FeedMetadata | null>(null);
	let feedMetadataTimestamp = $state<number | null>(null);
	let webrtcStatus = $state<
		'idle' | 'checking' | 'unavailable' | 'connecting' | 'connected' | 'error'
	>('idle');
	let webrtcTargetReady = $state(false);
	let webrtcBlockers = $state<string[]>([]);
	let rtcStream = $state<MediaStream | null>(null);
	const usingWebrtc = $derived(rtcStream !== null);
	let rtcVideo = $state<HTMLVideoElement | null>(null);
	let mediaContainer = $state<HTMLDivElement | null>(null);
	let mediaContainerWidth = $state(0);
	let mediaContainerHeight = $state(0);
	let retryTimer: ReturnType<typeof setTimeout> | null = null;
	let metadataRetryTimer: ReturnType<typeof setTimeout> | null = null;
	let metadataSocket: WebSocket | null = null;
	let webrtcLease: CameraWebrtcLease | null = null;
	let resizeObserver: ResizeObserver | null = null;

	function wsBaseFromHttpBase(httpBase: string): string {
		try {
			const parsed = new URL(httpBase);
			parsed.protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
			parsed.pathname = '';
			parsed.search = '';
			parsed.hash = '';
			return parsed.toString().replace(/\/$/, '');
		} catch {
			return httpBase.replace(/^http/, 'ws').replace(/\/$/, '');
		}
	}

	function numberValue(value: unknown): number | null {
		return typeof value === 'number' && Number.isFinite(value) ? value : null;
	}

	function pointList(value: unknown): Point[] {
		if (!Array.isArray(value)) return [];
		return value
			.map((point) => {
				if (!Array.isArray(point) || point.length < 2) return null;
				const x = numberValue(point[0]);
				const y = numberValue(point[1]);
				return x === null || y === null ? null : ([x, y] as Point);
			})
			.filter((point): point is Point => point !== null);
	}

	function polygonPoints(value: unknown): string | null {
		const points = pointList(value);
		if (points.length < 3) return null;
		return points.map(([x, y]) => `${x},${y}`).join(' ');
	}

	function bboxRect(
		value: unknown
	): { x: number; y: number; width: number; height: number } | null {
		if (!Array.isArray(value) || value.length < 4) return null;
		const x1 = numberValue(value[0]);
		const y1 = numberValue(value[1]);
		const x2 = numberValue(value[2]);
		const y2 = numberValue(value[3]);
		if (x1 === null || y1 === null || x2 === null || y2 === null) return null;
		const width = x2 - x1;
		const height = y2 - y1;
		if (width <= 0 || height <= 0) return null;
		return { x: x1, y: y1, width, height };
	}

	function viewportRect(value: FeedMetadataViewport | null | undefined): MediaViewport | null {
		if (!value) return null;
		const x = numberValue(value.x);
		const y = numberValue(value.y);
		const width = numberValue(value.width);
		const height = numberValue(value.height);
		if (x === null || y === null || width === null || height === null) return null;
		if (width <= 0 || height <= 0) return null;
		return { x, y, width, height };
	}

	function updateMediaContainerSize() {
		if (!mediaContainer) return;
		const rect = mediaContainer.getBoundingClientRect();
		mediaContainerWidth = Math.max(0, rect.width);
		mediaContainerHeight = Math.max(0, rect.height);
	}

	function closeMetadataSocket() {
		if (metadataSocket !== null) {
			metadataSocket.onopen = null;
			metadataSocket.onmessage = null;
			metadataSocket.onerror = null;
			metadataSocket.onclose = null;
			metadataSocket.close();
			metadataSocket = null;
		}
	}

	function handleMetadataPayload(payload: unknown) {
		const decision = decideCameraFeedMetadataUpdate(payload, feedMetadataTimestamp);
		if (decision.action === 'clear') {
			feedMetadata = null;
			feedMetadataTimestamp = null;
			return;
		}
		if (decision.action === 'ignore') {
			return;
		}
		feedMetadata = decision.metadata;
		if (decision.timestamp !== null) {
			feedMetadataTimestamp = decision.timestamp;
		}
	}

	function releaseWebrtcSession() {
		if (webrtcLease !== null) {
			webrtcLease.release();
			webrtcLease = null;
		}
		rtcStream = null;
	}

	onMount(() => {
		updateMediaContainerSize();
		const update = () => updateMediaContainerSize();
		if (typeof ResizeObserver !== 'undefined' && mediaContainer) {
			resizeObserver = new ResizeObserver(update);
			resizeObserver.observe(mediaContainer);
		}
		if (typeof window !== 'undefined') {
			window.addEventListener('resize', update);
		}
		return () => {
			if (resizeObserver !== null) {
				resizeObserver.disconnect();
				resizeObserver = null;
			}
			if (typeof window !== 'undefined') {
				window.removeEventListener('resize', update);
			}
		};
	});

	function handleFullscreenKey(event: KeyboardEvent) {
		if (event.key === 'Escape' && fullscreenOpen) {
			fullscreenOpen = false;
		}
	}

	function scheduleStreamRetry() {
		if (retryTimer !== null) return;
		const delayMs = health === 'online' || health === 'unknown' ? 1000 : 2500;
		retryTimer = setTimeout(() => {
			retryTimer = null;
			streamRetry += 1;
		}, delayMs);
	}

	onDestroy(() => {
		if (retryTimer !== null) {
			clearTimeout(retryTimer);
		}
		if (metadataRetryTimer !== null) {
			clearTimeout(metadataRetryTimer);
		}
		if (resizeObserver !== null) {
			resizeObserver.disconnect();
			resizeObserver = null;
		}
		closeMetadataSocket();
		releaseWebrtcSession();
	});

	const renderPolicy = $derived(
		cameraFeedRenderPolicy({
			direct,
			annotated,
			cropped,
			zones: effectiveZones,
			usingWebrtc
		})
	);
	const browserMetadataCandidate = $derived(renderPolicy.browserMetadataCandidate);
	const browserOverlayCandidate = $derived(renderPolicy.browserOverlayCandidate);
	const browserCropCandidate = $derived(renderPolicy.browserCropCandidate);
	const metadataWebsocketCandidate = $derived(renderPolicy.metadataWebsocketCandidate);
	const serverAnnotated = $derived(renderPolicy.serverAnnotated);
	const serverShowRegions = $derived(renderPolicy.serverShowRegions);
	const serverDashboard = $derived(renderPolicy.serverDashboard);

	const mjpegSrc = $derived.by(() => {
		const params = new URLSearchParams({
			annotated: serverAnnotated ? '1' : '0',
			layer: serverAnnotated ? 'annotated' : 'raw',
			direct: direct ? '1' : '0',
			dashboard: serverDashboard ? '1' : '0',
			show_regions: serverShowRegions ? '1' : '0',
			stream_epoch: String(ctx.machine?.cameraFeedEpoch ?? 0),
			stream_retry: String(streamRetry)
		});
		return `${effectiveBaseUrl()}/api/cameras/feed/${encodeURIComponent(camera)}?${params.toString()}`;
	});

	const metadataWsSrc = $derived.by(() => {
		const params = new URLSearchParams({
			show_regions: effectiveZones ? '1' : '0',
			interval_ms: '100',
			stream_epoch: String(ctx.machine?.cameraFeedEpoch ?? 0),
			metadata_retry: String(metadataRetry)
		});
		return `${wsBaseFromHttpBase(effectiveBaseUrl())}/ws/cameras/feed-metadata/${encodeURIComponent(
			camera
		)}?${params.toString()}`;
	});

	const overlayFrame = $derived.by(() => {
		const frame = feedMetadata?.frame;
		const width = numberValue(frame?.width);
		const height = numberValue(frame?.height);
		if (width === null || height === null || width <= 0 || height <= 0) return null;
		return { width, height };
	});

	const cropViewport = $derived.by<MediaViewport | null>(() => {
		if (!browserCropCandidate || !feedMetadata?.ok || !feedMetadata.crop?.available) return null;
		return viewportRect(feedMetadata.crop.viewport);
	});

	const mediaViewport = $derived.by<MediaViewport | null>(() => {
		if (!overlayFrame) return null;
		return (
			cropViewport ?? {
				x: 0,
				y: 0,
				width: overlayFrame.width,
				height: overlayFrame.height
			}
		);
	});

	const mediaLayout = $derived.by<MediaLayout | null>(() => {
		if (!overlayFrame || !mediaViewport || mediaContainerWidth <= 0 || mediaContainerHeight <= 0) {
			return null;
		}
		const scale = Math.min(
			mediaContainerWidth / mediaViewport.width,
			mediaContainerHeight / mediaViewport.height
		);
		if (!Number.isFinite(scale) || scale <= 0) return null;

		const viewportDisplayWidth = mediaViewport.width * scale;
		const viewportDisplayHeight = mediaViewport.height * scale;
		const viewportLeft = (mediaContainerWidth - viewportDisplayWidth) / 2;
		const viewportTop = (mediaContainerHeight - viewportDisplayHeight) / 2;
		const imageLeft = viewportLeft - mediaViewport.x * scale;
		const imageTop = viewportTop - mediaViewport.y * scale;

		return {
			imageStyle: [
				`left: ${imageLeft}px`,
				`top: ${imageTop}px`,
				`width: ${overlayFrame.width * scale}px`,
				`height: ${overlayFrame.height * scale}px`
			].join('; '),
			overlayStyle: [
				`left: ${viewportLeft}px`,
				`top: ${viewportTop}px`,
				`width: ${viewportDisplayWidth}px`,
				`height: ${viewportDisplayHeight}px`
			].join('; '),
			viewBox: `${mediaViewport.x} ${mediaViewport.y} ${mediaViewport.width} ${mediaViewport.height}`
		};
	});

	const overlayItems = $derived.by<OverlayItem[]>(() => {
		if (!browserOverlayCandidate || !feedMetadata?.ok || !overlayFrame) return [];
		const items: OverlayItem[] = [];
		for (const [index, overlay] of (feedMetadata.overlays ?? []).entries()) {
			const category = String(overlay.category ?? '');
			if (category === 'regions') {
				if (!effectiveZones) continue;
				const points = polygonPoints(overlay.polygon);
				if (points) {
					items.push({
						kind: 'polygon',
						points,
						category,
						key: `${category}:${overlay.poly_key ?? 'polygon'}:${index}`
					});
				}
				continue;
			}
			if (category === 'detections' || overlay.type === 'track_bbox') {
				if (!annotated) continue;
				const rect = bboxRect(overlay.bbox);
				if (rect) {
					items.push({
						kind: 'bbox',
						...rect,
						label: String(overlay.label ?? ''),
						key: `${category}:${overlay.label ?? 'bbox'}:${index}`
					});
				}
			}
		}
		return items;
	});

	$effect(() => {
		if (!metadataWebsocketCandidate || typeof WebSocket === 'undefined') {
			feedMetadata = null;
			feedMetadataTimestamp = null;
			closeMetadataSocket();
			return;
		}
		const url = metadataWsSrc;
		let closedByEffect = false;
		closeMetadataSocket();
		const socket = new WebSocket(url);
		metadataSocket = socket;
		socket.onmessage = (message) => {
			try {
				handleMetadataPayload(JSON.parse(message.data));
			} catch {
				feedMetadata = null;
				feedMetadataTimestamp = null;
			}
		};
		socket.onclose = () => {
			if (metadataSocket === socket) metadataSocket = null;
			if (!closedByEffect && metadataRetryTimer === null) {
				metadataRetryTimer = setTimeout(() => {
					metadataRetryTimer = null;
					metadataRetry += 1;
				}, 1000);
			}
		};
		socket.onerror = () => {
			socket.close();
		};
		return () => {
			closedByEffect = true;
			if (metadataSocket === socket) {
				closeMetadataSocket();
			} else {
				socket.close();
			}
		};
	});

	const configuredSource = $derived(ctx.machine?.camerasConfig?.cameras?.[camera]);
	const hasCameraConfig = $derived(Boolean(ctx.machine?.camerasConfig?.cameras));
	const health = $derived(
		ctx.cameraHealth.get(camera) ??
			(hasCameraConfig && configuredSource == null ? 'unassigned' : 'unknown')
	);
	const is_healthy = $derived(health === 'online' || health === 'unknown');
	const is_configured = $derived(health !== 'unassigned');
	const webrtcCandidate = $derived(
		webrtcTransportCandidate({
			preferWebrtc,
			isConfigured: is_configured
		})
	);
	const legacyMjpegAllowed = $derived(
		legacyMjpegFallbackAllowed({
			webrtcCandidate,
			webrtcTargetReady,
			webrtcStatus
		})
	);

	$effect(() => {
		if (!rtcVideo) return;
		rtcVideo.srcObject = rtcStream;
		if (rtcStream !== null) {
			void rtcVideo.play().catch(() => {
				// Autoplay may be temporarily blocked; the element is muted and will
				// retry naturally when the browser allows playback.
			});
		}
	});

	// Re-run the WebRTC session effect ONLY when the session identity actually
	// changes — not on every reactive churn of effectiveBaseUrl()'s inputs. A
	// $derived propagates only when its VALUE changes, so if base URL / role /
	// epoch resolve to the same key the effect does not re-run and does not tear
	// the session down. Tearing it down mid-handshake was calling closePeer(),
	// which aborts the in-flight /webrtc/offer fetch — so every offer was
	// aborted ~80-470ms in and the feed stayed stuck on "Connecting camera".
	const webrtcSessionKey = $derived(
		webrtcCandidate && typeof fetch !== 'undefined'
			? `${effectiveBaseUrl()}\n${camera}\n${String(ctx.machine?.cameraFeedEpoch ?? 0)}`
			: null
	);

	$effect(() => {
		const key = webrtcSessionKey;
		if (key === null) {
			webrtcTargetReady = false;
			webrtcBlockers = [];
			webrtcStatus = 'idle';
			untrack(() => releaseWebrtcSession());
			return;
		}
		const [httpBase, role, streamEpoch] = key.split('\n');
		untrack(() => releaseWebrtcSession());
		const lease = acquireCameraWebrtcSession(
			{ baseUrl: httpBase, camera: role, streamEpoch },
			{
				onState: (state) => {
					webrtcStatus = state.status;
					webrtcTargetReady = state.targetReady;
					webrtcBlockers = state.blockers;
					rtcStream = state.stream;
				},
				onMetadata: handleMetadataPayload
			}
		);
		webrtcLease = lease;
		return () => {
			if (webrtcLease === lease) {
				untrack(() => releaseWebrtcSession());
			} else {
				lease.release();
			}
		};
	});

	const display_label = $derived(label || camera);
</script>

<div
	class={`flex h-full min-h-0 flex-col overflow-hidden ${
		fullscreenOpen
			? 'fixed inset-0 z-50 !h-screen !w-screen bg-black p-4'
			: framed
				? 'setup-card-shell border'
				: 'setup-card-body'
	}`}
>
	{#if showHeader}
		<div
			class="setup-card-header flex flex-shrink-0 items-center justify-between px-3 py-2 text-sm"
		>
			<span class="font-medium text-text">{display_label}</span>
		</div>
	{/if}
	<div
		bind:this={mediaContainer}
		class={`relative flex-1 overflow-hidden ${showOverlay ? 'bg-[#04070B]' : 'setup-card-body'}`}
	>
		{#if is_configured}
			{#if usingWebrtc && mediaLayout}
				<video
					bind:this={rtcVideo}
					autoplay
					muted
					playsinline
					class="absolute max-w-none"
					class:opacity-30={!is_healthy}
					style={mediaLayout.imageStyle}
				></video>
			{:else if usingWebrtc}
				<video
					bind:this={rtcVideo}
					autoplay
					muted
					playsinline
					class="absolute inset-0 h-full w-full object-contain"
					class:opacity-30={!is_healthy}
				></video>
			{:else if legacyMjpegAllowed && mediaLayout}
				<img
					src={mjpegSrc}
					alt={display_label}
					class="absolute max-w-none"
					class:opacity-30={!is_healthy}
					style={mediaLayout.imageStyle}
					onerror={scheduleStreamRetry}
				/>
			{:else if legacyMjpegAllowed}
				<img
					src={mjpegSrc}
					alt={display_label}
					class="absolute inset-0 h-full w-full object-contain"
					class:opacity-30={!is_healthy}
					onerror={scheduleStreamRetry}
				/>
			{:else}
				<div class="absolute inset-0 flex items-center justify-center">
					<div class="flex flex-col items-center gap-2 text-center">
						<Loader2 size={28} class="animate-spin text-text-muted" />
						<span class="text-sm font-medium text-text-muted">Connecting camera...</span>
					</div>
				</div>
			{/if}
		{/if}

		{#if browserOverlayCandidate && mediaLayout && overlayItems.length > 0}
			<svg
				class="pointer-events-none absolute"
				style={mediaLayout.overlayStyle}
				viewBox={mediaLayout.viewBox}
				preserveAspectRatio="xMidYMid meet"
				aria-hidden="true"
			>
				{#each overlayItems as item (item.key)}
					{#if item.kind === 'polygon'}
						<polygon
							points={item.points}
							fill="rgba(14, 165, 178, 0.18)"
							stroke="rgba(0, 202, 255, 0.95)"
							stroke-width="2"
							vector-effect="non-scaling-stroke"
						/>
					{:else}
						<rect
							x={item.x}
							y={item.y}
							width={item.width}
							height={item.height}
							fill="transparent"
							stroke="rgba(57, 255, 136, 0.96)"
							stroke-width="2"
							vector-effect="non-scaling-stroke"
						/>
						{#if item.label}
							<text
								x={item.x}
								y={Math.max(12, item.y - 5)}
								fill="rgba(235, 255, 241, 0.98)"
								stroke="rgba(0, 0, 0, 0.72)"
								stroke-width="3"
								paint-order="stroke"
								font-size="13"
								font-weight="700"
								vector-effect="non-scaling-stroke"
							>
								{item.label}
							</text>
						{/if}
					{/if}
				{/each}
			</svg>
		{/if}

		{#if !is_healthy}
			<div class="absolute inset-0 flex items-center justify-center">
				<div class="flex flex-col items-center gap-2 text-center">
					{#if health === 'reconnecting'}
						<Loader2 size={28} class="animate-spin text-text-muted" />
						<span class="text-sm font-medium text-text-muted">Reconnecting...</span>
					{:else if health === 'offline'}
						<WifiOff size={28} class="text-text-muted" />
						<span class="text-sm font-medium text-text-muted">Camera Offline</span>
					{:else if health === 'unassigned'}
						<VideoOff size={28} class="text-text-muted" />
						<span class="text-sm font-medium text-text-muted">No Camera Assigned</span>
					{/if}
				</div>
			</div>
		{/if}

		<StreamControlsOverlay
			bind:annotated
			bind:cropped
			bind:zones
			bind:fullscreen={fullscreenOpen}
			{showAnnotations}
			{showCrop}
			{showZones}
			{showFullscreen}
		/>

		{#if showOverlay}
			<div
				class="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-black/55 via-black/12 to-transparent"
			></div>
			<div
				class="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black/72 via-black/14 to-transparent"
			></div>

			<div
				class="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3"
			>
				<div
					class="rounded-full border border-white/12 bg-black/55 px-3 py-1 text-xs font-semibold tracking-[0.16em] text-white/90 uppercase backdrop-blur-sm"
				>
					{display_label}
				</div>
			</div>

			<div
				class="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3"
			>
				<div
					class="rounded-full border border-white/12 bg-black/50 px-3 py-1 text-xs font-medium text-white/75 backdrop-blur-sm"
				>
					{annotated ? 'Annotated' : 'Raw'} — MJPEG
				</div>
			</div>
		{/if}

		{#if fullscreenOpen}
			<div
				class="pointer-events-none absolute top-3 left-3 z-20 border border-white/20 bg-black/55 px-2 py-0.5 text-xs text-white/80 shadow-md backdrop-blur-sm"
			>
				Esc or toggle to exit
			</div>
		{/if}
	</div>
</div>

<svelte:window onkeydown={handleFullscreenKey} />

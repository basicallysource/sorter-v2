<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import {
		acquireCameraWebrtcSession,
		type CameraWebrtcLease
	} from '$lib/camera/webrtc-session';
	import {
		legacyMjpegFallbackAllowed,
		webrtcTransportCandidate
	} from '$lib/camera/transport-policy';
	import { createEventDispatcher, onDestroy, untrack } from 'svelte';

	type MediaSizeEvent = {
		width: number;
		height: number;
		kind: 'image' | 'video';
	};

	let {
		camera,
		baseUrl,
		mjpegSrc,
		alt = '',
		mediaClass = '',
		mediaStyle = '',
		preferWebrtc = true,
		isConfigured = true,
		streamEpoch = undefined
	}: {
		camera: string;
		baseUrl: string;
		mjpegSrc: string;
		alt?: string;
		mediaClass?: string;
		mediaStyle?: string;
		preferWebrtc?: boolean;
		isConfigured?: boolean;
		streamEpoch?: string | number;
	} = $props();

	const ctx = getMachineContext();
	const dispatch = createEventDispatcher<{ mediasize: MediaSizeEvent }>();

	let webrtcStatus = $state<
		'idle' | 'checking' | 'unavailable' | 'connecting' | 'connected' | 'error'
	>('idle');
	let webrtcTargetReady = $state(false);
	let rtcStream = $state<MediaStream | null>(null);
	let rtcVideo = $state<HTMLVideoElement | null>(null);
	let mjpegImage = $state<HTMLImageElement | null>(null);
	let webrtcLease: CameraWebrtcLease | null = null;
	let mjpegRetry = $state(0);
	let retryTimer: ReturnType<typeof setTimeout> | null = null;

	const effectiveStreamEpoch = $derived(streamEpoch ?? ctx.machine?.cameraFeedEpoch ?? 0);
	const usingWebrtc = $derived(rtcStream !== null);
	const webrtcCandidate = $derived(
		webrtcTransportCandidate({
			preferWebrtc,
			isConfigured
		})
	);
	const legacyMjpegAllowed = $derived(
		legacyMjpegFallbackAllowed({
			webrtcCandidate,
			webrtcTargetReady,
			webrtcStatus
		})
	);
	const fallbackMjpegSrc = $derived.by(() => {
		if (mjpegRetry <= 0) return mjpegSrc;
		const separator = mjpegSrc.includes('?') ? '&' : '?';
		return `${mjpegSrc}${separator}transport_retry=${mjpegRetry}`;
	});

	function reportMediaSize(width: number, height: number, kind: 'image' | 'video') {
		if (width <= 0 || height <= 0) return;
		dispatch('mediasize', { width, height, kind });
	}

	function reportVideoSize(video: HTMLVideoElement | null) {
		if (!video) return;
		reportMediaSize(video.videoWidth, video.videoHeight, 'video');
	}

	function reportImageSize(image: HTMLImageElement | null) {
		if (!image) return;
		reportMediaSize(image.naturalWidth, image.naturalHeight, 'image');
	}

	function scheduleMjpegRetry() {
		if (retryTimer !== null) return;
		retryTimer = setTimeout(() => {
			retryTimer = null;
			mjpegRetry += 1;
		}, 1000);
	}

	function releaseWebrtcSession() {
		if (webrtcLease !== null) {
			webrtcLease.release();
			webrtcLease = null;
		}
		rtcStream = null;
	}

	$effect(() => {
		if (!rtcVideo) return;
		rtcVideo.srcObject = rtcStream;
		if (rtcStream !== null) {
			void rtcVideo.play().catch(() => {
				// Muted inline video can still be delayed by browser autoplay policy.
			});
			reportVideoSize(rtcVideo);
		}
	});

	$effect(() => {
		if (!webrtcCandidate || typeof fetch === 'undefined') {
			webrtcTargetReady = false;
			webrtcStatus = 'idle';
			untrack(() => releaseWebrtcSession());
			return;
		}
		const lease = acquireCameraWebrtcSession(
			{
				baseUrl,
				camera,
				streamEpoch: effectiveStreamEpoch
			},
			{
				onState: (state) => {
					webrtcStatus = state.status;
					webrtcTargetReady = state.targetReady;
					rtcStream = state.stream;
				}
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

	onDestroy(() => {
		if (retryTimer !== null) {
			clearTimeout(retryTimer);
			retryTimer = null;
		}
		releaseWebrtcSession();
	});
</script>

{#if usingWebrtc}
	<video
		bind:this={rtcVideo}
		autoplay
		muted
		playsinline
		class={mediaClass}
		style={mediaStyle}
		onloadedmetadata={(event) => reportVideoSize(event.currentTarget)}
		onresize={(event) => reportVideoSize(event.currentTarget)}
	></video>
{:else if legacyMjpegAllowed}
	<img
		bind:this={mjpegImage}
		src={fallbackMjpegSrc}
		{alt}
		class={mediaClass}
		style={mediaStyle}
		onload={() => reportImageSize(mjpegImage)}
		onerror={scheduleMjpegRetry}
	/>
{:else}
	<div class="absolute inset-0 flex items-center justify-center text-sm text-white/70">
		Connecting camera...
	</div>
{/if}

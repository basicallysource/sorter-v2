import { decideCameraFeedMetadataUpdate } from './metadata-sync';

export type CameraWebrtcStatus =
	| 'idle'
	| 'checking'
	| 'unavailable'
	| 'connecting'
	| 'connected'
	| 'error';

export type CameraWebrtcState = {
	status: CameraWebrtcStatus;
	targetReady: boolean;
	blockers: string[];
	stream: MediaStream | null;
};

export type CameraWebrtcSubscriber = {
	onState: (state: CameraWebrtcState) => void;
	onMetadata?: (payload: unknown) => void;
};

export type CameraWebrtcLease = {
	release: () => void;
};

type CameraWebrtcAcquireOptions = {
	baseUrl: string;
	camera: string;
	streamEpoch?: string | number;
};

type MetadataDataChannelSpec = {
	label?: string;
	ordered?: boolean;
	max_retransmits?: number;
};

type WebRtcSession = {
	physical_source?: string;
	roles?: string[];
};

type WebRtcSessionsPayload = {
	ok?: boolean;
	target_ready?: boolean;
	blockers?: unknown;
	sessions?: WebRtcSession[];
	control_plane?: {
		metadata_data_channel?: MetadataDataChannelSpec;
	};
};

type WebRtcOfferResponse = {
	type?: string;
	sdp?: string;
};

const sessions = new Map<string, SharedCameraWebrtcSession>();
const directoryRequests = new Map<string, Promise<WebRtcSessionsPayload | null>>();

export function __cameraWebrtcSessionDebug() {
	const sessionSubscriberCounts: Record<string, number> = {};
	const sessionStatuses: Record<string, CameraWebrtcStatus> = {};
	for (const [key, session] of sessions.entries()) {
		sessionSubscriberCounts[key] = session.subscriberCount;
		sessionStatuses[key] = session.status;
	}
	return {
		sessionCount: sessions.size,
		sessionKeys: [...sessions.keys()].sort(),
		sessionSubscriberCounts,
		sessionStatuses,
		directoryRequestCount: directoryRequests.size
	};
}

export function __resetCameraWebrtcSessionsForTests() {
	for (const session of sessions.values()) {
		session.close();
	}
	sessions.clear();
	directoryRequests.clear();
}

// Close peers eagerly when the page goes away. Without this the server only
// notices dead peers via ICE timeout seconds later — a reload's new offers
// then collide with the old page's still-registered encoders and get 503'd.
if (typeof window !== 'undefined') {
	window.addEventListener('pagehide', () => {
		for (const session of sessions.values()) {
			session.close();
		}
		sessions.clear();
		directoryRequests.clear();
	});
}

function normalizeBaseUrl(baseUrl: string): string {
	return baseUrl.replace(/\/$/, '');
}

function streamEpochValue(streamEpoch: string | number | undefined): string {
	return String(streamEpoch ?? 0);
}

function sessionsUrl(baseUrl: string, streamEpoch: string): string {
	const params = new URLSearchParams({ stream_epoch: streamEpoch });
	return `${baseUrl}/api/cameras/webrtc/sessions?${params.toString()}`;
}

function offerUrl(baseUrl: string, camera: string): string {
	return `${baseUrl}/api/cameras/webrtc/offer/${encodeURIComponent(camera)}`;
}

function stringList(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

async function readJson(response: Response): Promise<unknown> {
	try {
		return await response.json();
	} catch {
		return null;
	}
}

async function fetchSessionsPayload(
	baseUrl: string,
	streamEpoch: string,
	signal?: AbortSignal
): Promise<WebRtcSessionsPayload | null> {
	const response = await fetch(sessionsUrl(baseUrl, streamEpoch), { signal });
	const payload = (await readJson(response)) as WebRtcSessionsPayload | null;
	if (!response.ok || !payload?.ok) return null;
	return payload;
}

function directoryKey(baseUrl: string, streamEpoch: string): string {
	return `${baseUrl}|${streamEpoch}`;
}

function sharedSessionKey(
	baseUrl: string,
	camera: string,
	streamEpoch: string,
	payload: WebRtcSessionsPayload | null
): string {
	for (const session of payload?.sessions ?? []) {
		if (session.roles?.includes(camera) && session.physical_source) {
			return `${baseUrl}|physical:${session.physical_source}|${streamEpoch}`;
		}
	}
	return `${baseUrl}|role:${camera}|${streamEpoch}`;
}

function sharedDirectoryPayload(
	baseUrl: string,
	streamEpoch: string
): Promise<WebRtcSessionsPayload | null> {
	const key = directoryKey(baseUrl, streamEpoch);
	const existing = directoryRequests.get(key);
	if (existing) return existing;
	const request = fetchSessionsPayload(baseUrl, streamEpoch)
		.catch(() => null)
		.finally(() => {
			if (directoryRequests.get(key) === request) {
				directoryRequests.delete(key);
			}
		});
	directoryRequests.set(key, request);
	return request;
}

function notifySubscriber(subscriber: CameraWebrtcSubscriber, state: CameraWebrtcState) {
	try {
		subscriber.onState({
			status: state.status,
			targetReady: state.targetReady,
			blockers: [...state.blockers],
			stream: state.stream
		});
	} catch {
		// UI callbacks are best-effort; one broken consumer must not tear down
		// the shared camera transport for the remaining consumers.
	}
}

export function acquireCameraWebrtcSession(
	options: CameraWebrtcAcquireOptions,
	subscriber: CameraWebrtcSubscriber
): CameraWebrtcLease {
	const baseUrl = normalizeBaseUrl(options.baseUrl);
	const streamEpoch = streamEpochValue(options.streamEpoch);
	let released = false;
	let activeSession: SharedCameraWebrtcSession | null = null;

	notifySubscriber(subscriber, {
		status: 'checking',
		targetReady: false,
		blockers: [],
		stream: null
	});

	void sharedDirectoryPayload(baseUrl, streamEpoch).then((payload) => {
		if (released) return;
		const key = sharedSessionKey(baseUrl, options.camera, streamEpoch, payload);
		let session = sessions.get(key);
		if (!session) {
			session = new SharedCameraWebrtcSession({
				key,
				baseUrl,
				offerCamera: options.camera,
				streamEpoch,
				initialSessionsPayload: payload
			});
			sessions.set(key, session);
		}
		activeSession = session;
		session.subscribe(subscriber);
	});

	return {
		release() {
			released = true;
			if (activeSession) {
				activeSession.unsubscribe(subscriber);
				activeSession = null;
			}
		}
	};
}

class SharedCameraWebrtcSession {
	private readonly key: string;
	private readonly baseUrl: string;
	private readonly offerCamera: string;
	private readonly streamEpoch: string;
	private initialSessionsPayload: WebRtcSessionsPayload | null | undefined;
	private readonly subscribers = new Set<CameraWebrtcSubscriber>();
	private state: CameraWebrtcState = {
		status: 'idle',
		targetReady: false,
		blockers: [],
		stream: null
	};
	private peer: RTCPeerConnection | null = null;
	private metadataChannel: RTCDataChannel | null = null;
	private metadataTimestamp: number | null = null;
	private abortController: AbortController | null = null;
	private retryTimer: ReturnType<typeof setTimeout> | null = null;
	private retryAttempt = 0;
	private negotiationInFlight = false;
	private closed = false;

	constructor({
		key,
		baseUrl,
		offerCamera,
		streamEpoch,
		initialSessionsPayload
	}: {
		key: string;
		baseUrl: string;
		offerCamera: string;
		streamEpoch: string;
		initialSessionsPayload?: WebRtcSessionsPayload | null;
	}) {
		this.key = key;
		this.baseUrl = baseUrl;
		this.offerCamera = offerCamera;
		this.streamEpoch = streamEpoch;
		this.initialSessionsPayload = initialSessionsPayload;
	}

	subscribe(subscriber: CameraWebrtcSubscriber) {
		this.subscribers.add(subscriber);
		notifySubscriber(subscriber, this.state);
		// Kick a fresh subscriber's session when it is idle OR stuck in a
		// terminal failure — so attaching to an already-errored shared session
		// recovers immediately instead of waiting out the retry timer.
		if (this.canStart && !this.negotiationInFlight) {
			this.start();
		}
	}

	get subscriberCount(): number {
		return this.subscribers.size;
	}

	get status(): CameraWebrtcStatus {
		return this.state.status;
	}

	unsubscribe(subscriber: CameraWebrtcSubscriber) {
		this.subscribers.delete(subscriber);
		if (this.subscribers.size === 0) {
			this.close();
			if (sessions.get(this.key) === this) {
				sessions.delete(this.key);
			}
		}
	}

	// A session may (re)negotiate only from a terminal/idle state. Crucially it
	// must NOT start while a peer is already 'connected' or mid-'connecting':
	// a stale retry timer firing there would re-enter negotiate(), which clears
	// the live stream and calls closePeer() — tearing down the very peer that is
	// streaming H.264, right as the track would render. (checking/connecting are
	// also covered by negotiationInFlight during active negotiation, but the
	// window between negotiate() resolving and ontrack firing is not.)
	private get canStart(): boolean {
		return (
			this.state.status === 'idle' ||
			this.state.status === 'error' ||
			this.state.status === 'unavailable'
		);
	}

	private start() {
		if (this.closed || this.negotiationInFlight || this.subscribers.size === 0 || !this.canStart)
			return;
		if (this.retryTimer !== null) {
			clearTimeout(this.retryTimer);
			this.retryTimer = null;
		}
		this.negotiationInFlight = true;
		void this.negotiate()
			.catch((err) => {
				if (this.closed) return;
				this.setState({
					status: 'error',
					targetReady: false,
					blockers: [err instanceof Error ? err.message : 'WebRTC negotiation failed.'],
					stream: null
				});
				this.closePeer();
				this.scheduleRetry(5000);
			})
			.finally(() => {
				this.negotiationInFlight = false;
			});
	}

	private async negotiate() {
		this.setState({
			status: 'checking',
			targetReady: false,
			blockers: [],
			stream: null
		});
		const controller = new AbortController();
		this.abortController = controller;
		const sessionsPayload =
			this.initialSessionsPayload ??
			(await fetchSessionsPayload(this.baseUrl, this.streamEpoch, controller.signal));
		this.initialSessionsPayload = undefined;
		if (!sessionsPayload) {
			this.setState({
				status: 'error',
				targetReady: false,
				blockers: ['WebRTC session status is unavailable.'],
				stream: null
			});
			this.scheduleRetry(5000);
			return;
		}

		const targetReady = Boolean(sessionsPayload.target_ready);
		const blockers = stringList(sessionsPayload.blockers);
		if (!targetReady) {
			this.setState({
				status: 'unavailable',
				targetReady,
				blockers,
				stream: null
			});
			this.closePeer();
			this.scheduleRetry(10000);
			return;
		}
		if (typeof RTCPeerConnection === 'undefined') {
			this.setState({
				status: 'error',
				targetReady,
				blockers: ['Browser RTCPeerConnection is unavailable.'],
				stream: null
			});
			this.scheduleRetry(10000);
			return;
		}

		this.setState({ ...this.state, status: 'connecting', targetReady, blockers });
		const peer = new RTCPeerConnection();
		this.peer = peer;
		peer.addTransceiver('video', { direction: 'recvonly' });
		const dataChannelSpec = sessionsPayload.control_plane?.metadata_data_channel ?? {};
		const metadataChannel = peer.createDataChannel(dataChannelSpec.label || 'camera-metadata', {
			ordered: dataChannelSpec.ordered ?? false,
			maxRetransmits:
				typeof dataChannelSpec.max_retransmits === 'number'
					? dataChannelSpec.max_retransmits
					: 0
		});
		this.attachMetadataChannel(metadataChannel, dataChannelSpec.label || 'camera-metadata');
		peer.ondatachannel = (event) => {
			if (event.channel.label !== (dataChannelSpec.label || 'camera-metadata')) return;
			this.attachMetadataChannel(event.channel, dataChannelSpec.label || 'camera-metadata');
		};
		peer.ontrack = (event) => {
			const stream = event.streams[0] ?? new MediaStream([event.track]);
			// A live track means the path recovered — reset the backoff so the
			// next transient (e.g. a camera switch) retries promptly again.
			this.retryAttempt = 0;
			this.setState({
				status: 'connected',
				targetReady,
				blockers,
				stream
			});
		};
		peer.onconnectionstatechange = () => {
			if (peer.connectionState === 'failed' || peer.connectionState === 'closed') {
				if (!controller.signal.aborted && !this.closed) {
					this.setState({ ...this.state, status: 'error', stream: null });
					this.closePeer();
					this.scheduleRetry(3000);
				}
			}
		};
		peer.oniceconnectionstatechange = () => {
			if (peer.iceConnectionState === 'failed' && !controller.signal.aborted && !this.closed) {
				this.setState({ ...this.state, status: 'error', stream: null });
				this.closePeer();
				this.scheduleRetry(3000);
			}
		};

		const offer = await peer.createOffer();
		await peer.setLocalDescription(offer);
		await waitForIceGatheringComplete(peer, controller.signal);
		const localDescription = peer.localDescription;
		if (!localDescription?.sdp || controller.signal.aborted || this.closed) return;

		const answerResponse = await fetch(offerUrl(this.baseUrl, this.offerCamera), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				type: localDescription.type,
				sdp: localDescription.sdp
			}),
			signal: controller.signal
		});
		const answerPayload = (await readJson(answerResponse)) as
			| WebRtcOfferResponse
			| { detail?: { blockers?: unknown } }
			| null;
		if (!answerResponse.ok) {
			const detail = answerPayload && 'detail' in answerPayload ? answerPayload.detail : null;
			this.setState({
				status: answerResponse.status === 503 ? 'unavailable' : 'error',
				targetReady: answerResponse.status === 503 ? false : targetReady,
				blockers: stringList(detail?.blockers),
				stream: null
			});
			this.closePeer();
			this.scheduleRetry(answerResponse.status === 503 ? 2500 : 5000);
			return;
		}
		if (!answerPayload || !('sdp' in answerPayload) || !answerPayload.sdp || !answerPayload.type) {
			this.setState({
				status: 'error',
				targetReady,
				blockers: ['WebRTC answer payload is invalid.'],
				stream: null
			});
			this.closePeer();
			this.scheduleRetry(5000);
			return;
		}
		await peer.setRemoteDescription({
			type: answerPayload.type as RTCSdpType,
			sdp: answerPayload.sdp
		});
	}

	private attachMetadataChannel(channel: RTCDataChannel, expectedLabel: string) {
		if (channel.label !== expectedLabel) return;
		if (this.metadataChannel && this.metadataChannel !== channel) {
			this.metadataChannel.onmessage = null;
			this.metadataChannel.close();
		}
		this.metadataChannel = channel;
		channel.onmessage = (event) => {
			let payload: unknown = null;
			try {
				payload = JSON.parse(String(event.data));
			} catch {
				return;
			}
			const decision = decideCameraFeedMetadataUpdate(payload, this.metadataTimestamp);
			if (decision.action === 'ignore') return;
			if (decision.action === 'clear') {
				this.metadataTimestamp = null;
				this.broadcastMetadata(null);
				return;
			}
			this.metadataTimestamp = decision.timestamp ?? this.metadataTimestamp;
			this.broadcastMetadata(decision.metadata);
		};
	}

	private broadcastMetadata(payload: unknown) {
		for (const subscriber of this.subscribers) {
			try {
				subscriber.onMetadata?.(payload);
			} catch {
				// Metadata is opportunistic; the next frame will replace it.
			}
		}
	}

	private setState(state: CameraWebrtcState) {
		this.state = {
			status: state.status,
			targetReady: state.targetReady,
			blockers: [...state.blockers],
			stream: state.stream
		};
		for (const subscriber of this.subscribers) {
			notifySubscriber(subscriber, this.state);
		}
	}

	private scheduleRetry(delayMs: number) {
		if (this.closed || this.retryTimer !== null || this.subscribers.size === 0) return;
		// Capped exponential backoff with jitter. ``delayMs`` is the floor for
		// this failure class (e.g. 10s for 'unavailable'); repeated failures grow
		// it toward a 30s cap so a persistent transient cannot become a retry
		// storm that outpaces server-side peer teardown (the 0->35+ peer leak).
		const attempt = this.retryAttempt;
		this.retryAttempt = Math.min(attempt + 1, 8);
		const backoff = Math.min(30000, delayMs * Math.pow(2, attempt));
		const jitter = Math.random() * 0.3 * backoff;
		this.retryTimer = setTimeout(() => {
			this.retryTimer = null;
			this.start();
		}, Math.round(backoff + jitter));
	}

	close() {
		this.closed = true;
		if (this.retryTimer !== null) {
			clearTimeout(this.retryTimer);
			this.retryTimer = null;
		}
		this.closePeer();
	}

	private closePeer() {
		if (this.abortController) {
			this.abortController.abort();
			this.abortController = null;
		}
		if (this.metadataChannel) {
			this.metadataChannel.onmessage = null;
			this.metadataChannel.close();
			this.metadataChannel = null;
		}
		if (this.peer) {
			this.peer.ondatachannel = null;
			this.peer.ontrack = null;
			this.peer.onconnectionstatechange = null;
			this.peer.oniceconnectionstatechange = null;
			this.peer.close();
			this.peer = null;
		}
		if (this.state.stream) {
			for (const track of this.state.stream.getTracks()) {
				track.stop();
			}
			this.state = { ...this.state, stream: null };
		}
	}
}

async function waitForIceGatheringComplete(
	peer: RTCPeerConnection,
	signal: AbortSignal
): Promise<void> {
	if (peer.iceGatheringState === 'complete') return;
	await new Promise<void>((resolve, reject) => {
		const cleanup = () => {
			peer.removeEventListener('icegatheringstatechange', onStateChange);
			signal.removeEventListener('abort', onAbort);
		};
		const onAbort = () => {
			cleanup();
			reject(new DOMException('WebRTC negotiation aborted.', 'AbortError'));
		};
		const onStateChange = () => {
			if (peer.iceGatheringState === 'complete') {
				cleanup();
				resolve();
			}
		};
		peer.addEventListener('icegatheringstatechange', onStateChange);
		signal.addEventListener('abort', onAbort);
		setTimeout(() => {
			cleanup();
			resolve();
		}, 1500);
	});
}

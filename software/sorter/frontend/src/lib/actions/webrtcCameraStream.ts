export type WebRtcCameraStreamOptions = {
	baseUrl: string;
	role: string;
	annotated?: boolean;
	layer?: 'annotated' | 'raw';
	dashboard?: boolean;
	colorCorrect?: boolean;
	showRegions?: boolean;
	reconnectDelayMs?: number;
};

type NormalizedWebRtcCameraStreamOptions = {
	baseUrl: string;
	role: string;
	annotated: boolean;
	layer: 'annotated' | 'raw';
	dashboard: boolean;
	colorCorrect: boolean;
	showRegions: boolean;
	reconnectDelayMs: number;
};

const DEFAULT_RECONNECT_DELAY_MS = 1000;
const ICE_GATHERING_TIMEOUT_MS = 2500;

const sharedStreams = new Map<string, SharedCameraConnection>();

function normalizeOptions(options: WebRtcCameraStreamOptions): NormalizedWebRtcCameraStreamOptions {
	return {
		baseUrl: options.baseUrl.replace(/\/$/, ''),
		role: options.role,
		annotated: options.annotated ?? true,
		layer: options.layer ?? 'annotated',
		dashboard: options.dashboard ?? false,
		colorCorrect: options.colorCorrect ?? true,
		showRegions: options.showRegions ?? true,
		reconnectDelayMs: options.reconnectDelayMs ?? DEFAULT_RECONNECT_DELAY_MS
	};
}

function streamKey(options: NormalizedWebRtcCameraStreamOptions): string {
	return [
		options.baseUrl,
		options.role,
		options.annotated ? 'annotated' : 'raw',
		options.layer,
		options.dashboard ? 'dashboard' : 'full',
		options.colorCorrect ? 'color' : 'no-color',
		options.showRegions ? 'regions' : 'no-regions'
	].join('|');
}

function waitForIceGatheringComplete(peer: RTCPeerConnection): Promise<void> {
	if (peer.iceGatheringState === 'complete') return Promise.resolve();
	return new Promise((resolve) => {
		let done = false;
		const finish = () => {
			if (done) return;
			done = true;
			window.clearTimeout(timeout);
			peer.removeEventListener('icegatheringstatechange', handleChange);
			resolve();
		};
		const handleChange = () => {
			if (peer.iceGatheringState === 'complete') finish();
		};
		const timeout = window.setTimeout(finish, ICE_GATHERING_TIMEOUT_MS);
		peer.addEventListener('icegatheringstatechange', handleChange);
	});
}

class SharedCameraConnection {
	private readonly stream = new MediaStream();
	private readonly videos = new Set<HTMLVideoElement>();
	private peer: RTCPeerConnection | null = null;
	private refs = 0;
	private connecting = false;
	private closed = false;
	private reconnectTimer: number | null = null;

	constructor(
		private readonly key: string,
		private readonly options: NormalizedWebRtcCameraStreamOptions
	) {}

	acquire(video: HTMLVideoElement): () => void {
		this.refs += 1;
		this.videos.add(video);
		this.attach(video);
		void this.connect();
		return () => this.release(video);
	}

	private release(video: HTMLVideoElement): void {
		this.videos.delete(video);
		if (video.srcObject === this.stream) {
			video.pause();
			video.srcObject = null;
		}
		this.refs = Math.max(0, this.refs - 1);
		if (this.refs > 0) return;
		this.closed = true;
		if (this.reconnectTimer !== null) {
			window.clearTimeout(this.reconnectTimer);
			this.reconnectTimer = null;
		}
		this.closePeer();
		for (const track of this.stream.getTracks()) {
			this.stream.removeTrack(track);
			track.stop();
		}
		sharedStreams.delete(this.key);
	}

	private attach(video: HTMLVideoElement): void {
		video.autoplay = true;
		video.playsInline = true;
		video.muted = true;
		video.srcObject = this.stream;
		void video.play().catch(() => {
			// The stream will start once the browser allows playback.
		});
	}

	private attachAll(): void {
		for (const video of this.videos) {
			this.attach(video);
		}
	}

	private closePeer(): void {
		const peer = this.peer;
		this.peer = null;
		if (peer && peer.connectionState !== 'closed') {
			peer.close();
		}
	}

	private replaceVideoTrack(track: MediaStreamTrack): void {
		for (const existing of this.stream.getVideoTracks()) {
			this.stream.removeTrack(existing);
			existing.stop();
		}
		this.stream.addTrack(track);
		this.attachAll();
	}

	private scheduleReconnect(): void {
		if (this.closed || this.refs <= 0 || this.reconnectTimer !== null) return;
		this.reconnectTimer = window.setTimeout(() => {
			this.reconnectTimer = null;
			this.closePeer();
			void this.connect();
		}, this.options.reconnectDelayMs);
	}

	private dispatchMetadata(raw: string): void {
		let detail: unknown = raw;
		try {
			detail = JSON.parse(raw);
		} catch {
			// Keep the raw payload for non-JSON metadata.
		}
		for (const video of this.videos) {
			video.dispatchEvent(new CustomEvent('camera-metadata', { detail }));
		}
	}

	private async connect(): Promise<void> {
		if (this.closed || this.connecting || this.peer) return;
		if (typeof RTCPeerConnection === 'undefined') {
			this.scheduleReconnect();
			return;
		}
		this.connecting = true;
		const peer = new RTCPeerConnection({ iceServers: [] });
		this.peer = peer;

		peer.addTransceiver('video', { direction: 'recvonly' });
		const metadataChannel = peer.createDataChannel('camera-metadata');
		metadataChannel.onmessage = (event) => this.dispatchMetadata(String(event.data));

		peer.ontrack = (event) => {
			const [track] = event.streams[0]?.getVideoTracks() ?? [event.track];
			if (track) this.replaceVideoTrack(track);
		};
		peer.onconnectionstatechange = () => {
			if (this.peer !== peer) return;
			if (peer.connectionState === 'failed' || peer.connectionState === 'disconnected') {
				this.closePeer();
				this.scheduleReconnect();
			}
		};

		try {
			const offer = await peer.createOffer();
			await peer.setLocalDescription(offer);
			await waitForIceGatheringComplete(peer);
			const localDescription = peer.localDescription;
			if (!localDescription) {
				throw new Error('Missing local WebRTC description');
			}

			const response = await fetch(
				`${this.options.baseUrl}/api/cameras/webrtc/offer/${encodeURIComponent(this.options.role)}`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						sdp: localDescription.sdp,
						type: localDescription.type,
						annotated: this.options.annotated,
						layer: this.options.layer,
						dashboard: this.options.dashboard,
						color_correct: this.options.colorCorrect,
						show_regions: this.options.showRegions
					})
				}
			);
			if (!response.ok) {
				if (response.status === 404) {
					if (this.peer === peer) {
						this.closePeer();
					} else if (peer.connectionState !== 'closed') {
						peer.close();
					}
					return;
				}
				throw new Error(`WebRTC offer failed with ${response.status}`);
			}
			const answer = (await response.json()) as RTCSessionDescriptionInit;
			await peer.setRemoteDescription(answer);
		} catch {
			if (this.peer === peer) {
				this.closePeer();
			} else if (peer.connectionState !== 'closed') {
				peer.close();
			}
			this.scheduleReconnect();
		} finally {
			if (this.peer === peer) {
				this.connecting = false;
			} else {
				this.connecting = false;
			}
		}
	}
}

function acquireSharedStream(
	video: HTMLVideoElement,
	options: NormalizedWebRtcCameraStreamOptions
): { key: string; release: () => void } {
	const key = streamKey(options);
	let connection = sharedStreams.get(key);
	if (!connection) {
		connection = new SharedCameraConnection(key, options);
		sharedStreams.set(key, connection);
	}
	return { key, release: connection.acquire(video) };
}

export function webrtcCameraStream(
	node: HTMLVideoElement,
	initialOptions: WebRtcCameraStreamOptions
) {
	let options = normalizeOptions(initialOptions);
	let handle = acquireSharedStream(node, options);

	return {
		update(nextOptions: WebRtcCameraStreamOptions) {
			const normalized = normalizeOptions(nextOptions);
			const nextKey = streamKey(normalized);
			if (nextKey === handle.key) return;
			handle.release();
			options = normalized;
			handle = acquireSharedStream(node, options);
		},
		destroy() {
			handle.release();
		}
	};
}

// Live camera video: one websocket per backend at /ws/video, whatever the page
// shows. A view is "role/<role>" (a camera role's picture) or "index/<n>" (a
// picker's thumbnail of camera n). The page sends the whole set of views it
// wants whenever that set changes; the backend sends each frame as one binary
// message, u16 LE key length | key | f64 LE capture time | JPEG, a note
// {"view", "error"} for a view it cannot serve, and "{}" when it has had
// nothing to send for 2 s.
//
// The JPEG is only pixels. What is drawn over it comes beside it as data
// (backend server/routers/camera_feeds.py): {"layout"} with a role view's
// zones and crop before its first frame and whenever they change, and
// {"detections"} with the boxes of a frame perception inferred on, just
// before that frame. CameraPicture draws them.

/** A ring of points as a flat [x0, y0, x1, y1, ...], 0..1 across and down. */
export type Ring = number[];

export type FeedZones = {
	drop: Ring[];
	exit: Ring[];
	precise: Ring[];
	outline: Ring[];
	margin: Ring[];
	secondary: { type: string; rings: Ring[] }[];
};

/** How the dashboard crops a camera to its channel: the zone's polygons, and
 * the turn (degrees, counter-clockwise) that puts its drop zone at the top. */
export type FeedCrop = { polygons: Ring[]; rotation: number };

export type FeedLayout = { zones: FeedZones | null; crop: FeedCrop | null };

export type FeedBox = {
	kind: 'piece' | 'merged' | 'seen' | 'margin';
	box: [number, number, number, number];
	id?: number;
};

/** A frame: its JPEG, its capture time, and what perception found on it,
 * or null when it is the camera's own. */
export type FeedFrame = { jpeg: Blob; ts: number; boxes: FeedBox[] | null };

export type FeedListener = {
	frame: (frame: FeedFrame) => void;
	layout?: (layout: FeedLayout) => void;
};

const RETRY_MIN_MS = 250;
const RETRY_MAX_MS = 3000;
// After the last view goes, the socket waits this long for the next one.
const IDLE_CLOSE_MS = 2000;
// Nothing heard for this long: the socket is dead, however open it looks.
const SILENT_MS = 6000;

export function roleView(role: string): string {
	return `role/${role}`;
}

export function indexView(index: number): string {
	return `index/${index}`;
}

const sockets = new Map<string, VideoSocket>();

/** Gives the listener each new frame of a view, and its layout now and
 * whenever it changes, until the returned stop is called. */
export function watchVideo(baseUrl: string, view: string, listener: FeedListener): () => void {
	let socket = sockets.get(baseUrl);
	if (!socket) {
		socket = new VideoSocket(baseUrl);
		sockets.set(baseUrl, socket);
	}
	return socket.watch(view, listener);
}

const decoder = new TextDecoder();

class VideoSocket {
	private url: string;
	private ws: WebSocket | null = null;
	private views = new Map<string, Set<FeedListener>>();
	// The newest layout of each view, for a listener that comes after it.
	private layouts = new Map<string, FeedLayout>();
	// Detections waiting for their frame, which comes next.
	private detections = new Map<string, { ts: number; boxes: FeedBox[] }>();
	private retryMs = RETRY_MIN_MS;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private closeTimer: ReturnType<typeof setTimeout> | null = null;
	private resendTimer: ReturnType<typeof setTimeout> | null = null;

	constructor(baseUrl: string) {
		const url = new URL('/ws/video', baseUrl);
		url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
		this.url = url.toString();
		// A hidden page watches nothing. Unsubscribing is only a message.
		document.addEventListener('visibilitychange', () => this.send());
	}

	watch(view: string, listener: FeedListener): () => void {
		let listeners = this.views.get(view);
		if (!listeners) this.views.set(view, (listeners = new Set()));
		listeners.add(listener);
		const layout = this.layouts.get(view);
		if (layout) queueMicrotask(() => listeners.has(listener) && listener.layout?.(layout));
		if (this.closeTimer) clearTimeout(this.closeTimer);
		this.closeTimer = null;
		if (!this.ws && !this.reconnectTimer) this.open();
		queueMicrotask(() => this.send());
		return () => {
			listeners.delete(listener);
			if (listeners.size === 0 && this.views.get(view) === listeners) this.views.delete(view);
			queueMicrotask(() => this.send());
			if (this.views.size > 0 || this.closeTimer) return;
			this.closeTimer = setTimeout(() => {
				this.closeTimer = null;
				if (this.views.size === 0) this.ws?.close();
			}, IDLE_CLOSE_MS);
		};
	}

	private open(): void {
		const ws = new WebSocket(this.url);
		ws.binaryType = 'arraybuffer';
		this.ws = ws;
		let heardAt = performance.now();
		const silence = setInterval(() => {
			if (performance.now() - heardAt > SILENT_MS) ws.close();
		}, 1000);
		ws.onopen = () => {
			this.retryMs = RETRY_MIN_MS;
			this.send();
		};
		ws.onmessage = (event) => {
			heardAt = performance.now();
			this.receive(event.data);
		};
		ws.onclose = () => {
			clearInterval(silence);
			this.ws = null;
			this.detections.clear();
			if (this.views.size === 0) return;
			this.reconnectTimer = setTimeout(() => {
				this.reconnectTimer = null;
				if (this.views.size > 0 && !this.ws) this.open();
			}, this.retryMs);
			this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS);
		};
	}

	/** Tells the backend the whole set of views this page shows now. */
	private send(): void {
		if (this.ws?.readyState !== WebSocket.OPEN) return;
		const views = document.visibilityState === 'hidden' ? [] : [...this.views.keys()];
		this.ws.send(JSON.stringify({ views }));
	}

	private receive(data: ArrayBuffer | string): void {
		if (typeof data === 'string') {
			const note = JSON.parse(data) as {
				view?: string;
				error?: string;
				layout?: string;
				detections?: string;
				ts?: number;
				boxes?: FeedBox[];
				zones?: FeedZones | null;
				crop?: FeedCrop | null;
			};
			if (note.layout) {
				const layout = { zones: note.zones ?? null, crop: note.crop ?? null };
				this.layouts.set(note.layout, layout);
				for (const listener of this.views.get(note.layout) ?? []) listener.layout?.(layout);
				return;
			}
			if (note.detections) {
				this.detections.set(note.detections, { ts: note.ts ?? 0, boxes: note.boxes ?? [] });
				return;
			}
			if (!note.view) return;
			console.warn(`[video] ${note.view}: ${note.error}`);
			// The backend keeps no view it could not serve, so sending the same
			// set again retries it (its camera may be assigned by then).
			this.resendTimer ??= setTimeout(() => {
				this.resendTimer = null;
				this.send();
			}, RETRY_MAX_MS);
			return;
		}
		const header = new DataView(data);
		const keyLength = header.getUint16(0, true);
		const view = decoder.decode(new Uint8Array(data, 2, keyLength));
		const ts = header.getFloat64(2 + keyLength, true);
		const found = this.detections.get(view);
		this.detections.delete(view);
		const listeners = this.views.get(view);
		if (!listeners) return;
		const frame = {
			jpeg: new Blob([new Uint8Array(data, 10 + keyLength)], { type: 'image/jpeg' }),
			ts,
			boxes: found && found.ts === ts ? found.boxes : null
		};
		for (const listener of listeners) listener.frame(frame);
	}
}

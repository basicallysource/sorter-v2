// Live camera video: one websocket per backend at /ws/video, whatever the page
// shows. A view is "role/<role>?layer=annotated|raw&dashboard=0|1" (a role's
// preview) or "index/<n>" (a picker's thumbnail of camera n). The page sends
// the whole set of views it wants whenever that set changes; the backend sends
// each frame as one binary message, u16 LE key length | key | f64 LE capture
// time | JPEG, a note {"view", "error"} for a view it cannot serve, and "{}"
// when it has had nothing to send for 2 s.

type FrameListener = (jpeg: Blob) => void;

const RETRY_MIN_MS = 250;
const RETRY_MAX_MS = 3000;
// After the last view goes, the socket waits this long for the next one.
const IDLE_CLOSE_MS = 2000;
// Nothing heard for this long: the socket is dead, however open it looks.
const SILENT_MS = 6000;

export function roleView(role: string, annotated: boolean, dashboard: boolean): string {
	return `role/${role}?layer=${annotated ? 'annotated' : 'raw'}&dashboard=${dashboard ? 1 : 0}`;
}

export function indexView(index: number): string {
	return `index/${index}`;
}

const sockets = new Map<string, VideoSocket>();

/** Calls onFrame with each new JPEG of a view until the returned stop is called. */
export function watchVideo(baseUrl: string, view: string, onFrame: FrameListener): () => void {
	let socket = sockets.get(baseUrl);
	if (!socket) {
		socket = new VideoSocket(baseUrl);
		sockets.set(baseUrl, socket);
	}
	return socket.watch(view, onFrame);
}

const decoder = new TextDecoder();

class VideoSocket {
	private url: string;
	private ws: WebSocket | null = null;
	private views = new Map<string, Set<FrameListener>>();
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

	watch(view: string, onFrame: FrameListener): () => void {
		let listeners = this.views.get(view);
		if (!listeners) this.views.set(view, (listeners = new Set()));
		listeners.add(onFrame);
		if (this.closeTimer) clearTimeout(this.closeTimer);
		this.closeTimer = null;
		if (!this.ws && !this.reconnectTimer) this.open();
		queueMicrotask(() => this.send());
		return () => {
			listeners.delete(onFrame);
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
			const note = JSON.parse(data) as { view?: string; error?: string };
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
		const keyLength = new DataView(data).getUint16(0, true);
		const listeners = this.views.get(decoder.decode(new Uint8Array(data, 2, keyLength)));
		if (!listeners) return;
		const jpeg = new Blob([new Uint8Array(data, 10 + keyLength)], { type: 'image/jpeg' });
		for (const onFrame of listeners) onFrame(jpeg);
	}
}

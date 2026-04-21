// WebSocket JPEG preview action.
//
// Mirrors the surface of ``mjpegStream`` (status callback, reconnect,
// destroy) but backs the stream with a WebSocket instead of a multipart
// HTTP request. Used by the zone-section camera picker modal so we do not
// consume 6+ concurrent HTTP/1.1 connections, which otherwise starves other
// fetch() calls from the same origin and freezes the modal.
//
// Server contract:
//   - URL shape: ``ws(s)://host/ws/camera-preview/<device-index>``.
//   - Each binary message is exactly one JPEG frame (no multipart framing).
//   - Text messages are ignored.

export type WsJpegStatus = 'pending' | 'streaming' | 'failed';

export type WsJpegStreamOptions = {
	url: string;
	reconnectDelayMs?: number;
	firstFrameTimeoutMs?: number;
	maxAttempts?: number;
	onStatusChange?: (status: WsJpegStatus) => void;
};

const DEFAULT_RECONNECT_DELAY_MS = 500;
const DEFAULT_FIRST_FRAME_TIMEOUT_MS = 6000;

function normalizeOptions(options: string | WsJpegStreamOptions) {
	if (typeof options === 'string') {
		return {
			url: options,
			reconnectDelayMs: DEFAULT_RECONNECT_DELAY_MS,
			firstFrameTimeoutMs: DEFAULT_FIRST_FRAME_TIMEOUT_MS,
			maxAttempts: Number.POSITIVE_INFINITY,
			onStatusChange: undefined as ((status: WsJpegStatus) => void) | undefined
		};
	}
	return {
		url: options.url,
		reconnectDelayMs: options.reconnectDelayMs ?? DEFAULT_RECONNECT_DELAY_MS,
		firstFrameTimeoutMs: options.firstFrameTimeoutMs ?? DEFAULT_FIRST_FRAME_TIMEOUT_MS,
		maxAttempts: options.maxAttempts ?? Number.POSITIVE_INFINITY,
		onStatusChange: options.onStatusChange
	};
}

export function wsJpegStream(node: HTMLImageElement, initialOptions: string | WsJpegStreamOptions) {
	let options = normalizeOptions(initialOptions);
	let destroyed = false;
	let socket: WebSocket | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let firstFrameTimer: ReturnType<typeof setTimeout> | null = null;
	let blobUrl: string | null = null;
	let attempts = 0;
	let gotFirstFrame = false;
	let lastStatus: WsJpegStatus = 'pending';

	function setStatus(next: WsJpegStatus) {
		if (next === lastStatus) return;
		lastStatus = next;
		// Direct assignment — no object spread — per guidance (Svelte 5 rune
		// reactivity was getting confused by spread replacement upstream).
		options.onStatusChange?.(next);
	}

	function clearBlobUrl() {
		if (blobUrl) {
			URL.revokeObjectURL(blobUrl);
			blobUrl = null;
		}
	}

	function clearTimers() {
		if (reconnectTimer !== null) {
			window.clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
		if (firstFrameTimer !== null) {
			window.clearTimeout(firstFrameTimer);
			firstFrameTimer = null;
		}
	}

	function closeSocket() {
		if (socket) {
			// Remove listeners before close so we don't re-enter reconnect
			// logic from the forced teardown.
			socket.onopen = null;
			socket.onmessage = null;
			socket.onerror = null;
			socket.onclose = null;
			try {
				socket.close();
			} catch {
				// Browser throws on double-close in some states; ignore.
			}
			socket = null;
		}
	}

	function scheduleFirstFrameWatchdog() {
		if (destroyed) return;
		if (firstFrameTimer !== null) {
			window.clearTimeout(firstFrameTimer);
		}
		firstFrameTimer = setTimeout(() => {
			if (!gotFirstFrame) {
				// Treat as a soft failure — force reconnect (which may
				// ultimately flip to 'failed' once attempts exhaust).
				closeSocket();
				scheduleReconnect();
			}
		}, options.firstFrameTimeoutMs);
	}

	function scheduleReconnect() {
		if (destroyed) return;
		if (!gotFirstFrame && attempts >= options.maxAttempts) {
			setStatus('failed');
			return;
		}
		if (reconnectTimer !== null) {
			window.clearTimeout(reconnectTimer);
		}
		// Small exponential-ish backoff, capped so a flapping device still
		// recovers quickly once it comes back.
		const delayMs = Math.min(
			options.reconnectDelayMs * Math.max(1, attempts),
			3000
		);
		reconnectTimer = setTimeout(() => {
			connect();
		}, delayMs);
	}

	function publishFrame(buffer: ArrayBuffer) {
		clearBlobUrl();
		const blob = new Blob([buffer], { type: 'image/jpeg' });
		blobUrl = URL.createObjectURL(blob);
		node.src = blobUrl;
		gotFirstFrame = true;
		setStatus('streaming');
	}

	function connect() {
		if (destroyed) return;
		closeSocket();
		attempts += 1;
		if (!gotFirstFrame) setStatus('pending');
		scheduleFirstFrameWatchdog();

		try {
			socket = new WebSocket(options.url);
		} catch {
			socket = null;
			scheduleReconnect();
			return;
		}
		socket.binaryType = 'arraybuffer';

		socket.onopen = () => {
			// Nothing to do — server starts streaming after accept. Status
			// flips to 'streaming' when the first frame arrives.
		};

		socket.onmessage = (event) => {
			if (event.data instanceof ArrayBuffer) {
				publishFrame(event.data);
			}
			// Text messages are ignored by the current server contract.
		};

		socket.onerror = () => {
			// onclose will follow — handle reconnect there to avoid double
			// scheduling.
		};

		socket.onclose = () => {
			socket = null;
			if (destroyed) return;
			clearTimers();
			scheduleReconnect();
		};
	}

	connect();

	return {
		update(nextOptions: string | WsJpegStreamOptions) {
			const normalized = normalizeOptions(nextOptions);
			const urlChanged = normalized.url !== options.url;
			const changed =
				urlChanged ||
				normalized.reconnectDelayMs !== options.reconnectDelayMs ||
				normalized.firstFrameTimeoutMs !== options.firstFrameTimeoutMs ||
				normalized.maxAttempts !== options.maxAttempts;
			options = normalized;
			if (urlChanged) {
				attempts = 0;
				gotFirstFrame = false;
				setStatus('pending');
			}
			if (changed) {
				closeSocket();
				clearTimers();
				connect();
			}
		},
		destroy() {
			destroyed = true;
			clearTimers();
			closeSocket();
			clearBlobUrl();
			node.removeAttribute('src');
		}
	};
}

export type MjpegStreamOptions = {
	url: string;
	reconnectDelayMs?: number;
	stallTimeoutMs?: number;
	firstFrameTimeoutMs?: number;
	maxAttempts?: number;
	onStatusChange?: (status: 'pending' | 'streaming' | 'failed') => void;
};

const DEFAULT_RECONNECT_DELAY_MS = 350;
const DEFAULT_STALL_TIMEOUT_MS = 3000;
const DEFAULT_FIRST_FRAME_TIMEOUT_MS = 4000;
const MAX_BUFFER_BYTES = 512 * 1024;

function normalizeOptions(options: string | MjpegStreamOptions) {
	if (typeof options === 'string') {
		return {
			url: options,
			reconnectDelayMs: DEFAULT_RECONNECT_DELAY_MS,
			stallTimeoutMs: DEFAULT_STALL_TIMEOUT_MS,
			firstFrameTimeoutMs: DEFAULT_FIRST_FRAME_TIMEOUT_MS,
			maxAttempts: Number.POSITIVE_INFINITY,
			onStatusChange: undefined as ((status: 'pending' | 'streaming' | 'failed') => void) | undefined
		};
	}

	return {
		url: options.url,
		reconnectDelayMs: options.reconnectDelayMs ?? DEFAULT_RECONNECT_DELAY_MS,
		stallTimeoutMs: options.stallTimeoutMs ?? DEFAULT_STALL_TIMEOUT_MS,
		firstFrameTimeoutMs: options.firstFrameTimeoutMs ?? DEFAULT_FIRST_FRAME_TIMEOUT_MS,
		maxAttempts: options.maxAttempts ?? Number.POSITIVE_INFINITY,
		onStatusChange: options.onStatusChange
	};
}

function isAbortError(error: unknown): boolean {
	return error instanceof DOMException
		? error.name === 'AbortError'
		: typeof error === 'object' &&
				error !== null &&
				'name' in error &&
				(error as { name?: unknown }).name === 'AbortError';
}

function appendNonce(url: string, nonce: string): string {
	const separator = url.includes('?') ? '&' : '?';
	return `${url}${separator}mjpeg=${encodeURIComponent(nonce)}`;
}

function findMarker(buffer: Uint8Array, first: number, second: number, start = 0): number {
	for (let index = start; index + 1 < buffer.length; index += 1) {
		if (buffer[index] === first && buffer[index + 1] === second) {
			return index;
		}
	}
	return -1;
}

export function mjpegStream(node: HTMLImageElement, initialOptions: string | MjpegStreamOptions) {
	let options = normalizeOptions(initialOptions);
	let generation = 0;
	let destroyed = false;
	let controller: AbortController | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let watchdogTimer: ReturnType<typeof setTimeout> | null = null;
	let blobUrl: string | null = null;
	let attempts = 0;
	let gotFirstFrame = false;
	let lastStatus: 'pending' | 'streaming' | 'failed' = 'pending';

	function setStatus(next: 'pending' | 'streaming' | 'failed') {
		if (next === lastStatus) return;
		lastStatus = next;
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
		if (watchdogTimer !== null) {
			window.clearTimeout(watchdogTimer);
			watchdogTimer = null;
		}
	}

	function stopCurrentStream() {
		controller?.abort();
		controller = null;
		clearTimers();
	}

	function scheduleWatchdog(timeoutMs: number) {
		if (destroyed) return;
		if (watchdogTimer !== null) {
			window.clearTimeout(watchdogTimer);
		}
		watchdogTimer = setTimeout(() => {
			if (!gotFirstFrame && attempts >= options.maxAttempts) {
				setStatus('failed');
				stopCurrentStream();
				return;
			}
			restart();
		}, timeoutMs);
	}

	function publishFrame(jpeg: Uint8Array) {
		clearBlobUrl();
		const bytes = Uint8Array.from(jpeg);
		blobUrl = URL.createObjectURL(new Blob([bytes.buffer], { type: 'image/jpeg' }));
		node.src = blobUrl;
		gotFirstFrame = true;
		setStatus('streaming');
		scheduleWatchdog(options.stallTimeoutMs);
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
		reconnectTimer = setTimeout(() => {
			restart();
		}, options.reconnectDelayMs);
	}

	async function start(token: number) {
		controller = new AbortController();
		attempts += 1;
		if (!gotFirstFrame) setStatus('pending');
		scheduleWatchdog(options.firstFrameTimeoutMs);

		try {
			const response = await fetch(appendNonce(options.url, `${Date.now()}-${token}`), {
				signal: controller.signal,
				cache: 'no-store'
			});
			if (!response.ok || !response.body) {
				throw new Error(`MJPEG stream request failed with ${response.status}`);
			}

			const reader = response.body.getReader();
			let buffer = new Uint8Array(0);

			while (!destroyed && token === generation) {
				const { done, value } = await reader.read();
				if (done) {
					throw new Error('MJPEG stream ended');
				}
				if (!value || value.length === 0) {
					continue;
				}

				const nextBuffer = new Uint8Array(buffer.length + value.length);
				nextBuffer.set(buffer);
				nextBuffer.set(value, buffer.length);
				buffer = nextBuffer;

				let working = true;
				while (working) {
					const start = findMarker(buffer, 0xff, 0xd8);
					if (start === -1) {
						if (buffer.length > 1) {
							buffer = buffer.slice(-1);
						}
						break;
					}

					const end = findMarker(buffer, 0xff, 0xd9, start + 2);
					if (end === -1) {
						buffer = buffer.slice(start);
						break;
					}

					const frame = buffer.slice(start, end + 2);
					buffer = buffer.slice(end + 2);
					publishFrame(frame);
					working = buffer.length > 1;
				}

				if (buffer.length > MAX_BUFFER_BYTES) {
					buffer = buffer.slice(-MAX_BUFFER_BYTES);
				}
			}
		} catch (error) {
			if (!destroyed && token === generation && !isAbortError(error)) {
				scheduleReconnect();
			}
		}
	}

	function restart() {
		if (destroyed) return;
		stopCurrentStream();
		generation += 1;
		void start(generation);
	}

	restart();

	return {
		update(nextOptions: string | MjpegStreamOptions) {
			const normalized = normalizeOptions(nextOptions);
			const urlChanged = normalized.url !== options.url;
			const changed =
				urlChanged ||
				normalized.reconnectDelayMs !== options.reconnectDelayMs ||
				normalized.stallTimeoutMs !== options.stallTimeoutMs ||
				normalized.firstFrameTimeoutMs !== options.firstFrameTimeoutMs ||
				normalized.maxAttempts !== options.maxAttempts;
			options = normalized;
			if (urlChanged) {
				attempts = 0;
				gotFirstFrame = false;
				setStatus('pending');
			}
			if (changed) {
				restart();
			}
		},
		destroy() {
			destroyed = true;
			stopCurrentStream();
			clearBlobUrl();
			node.removeAttribute('src');
		}
	};
}

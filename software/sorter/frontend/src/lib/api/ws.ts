import type { SocketEvent } from './events';

export function connectWebSocket(
	url: string,
	onEvent: (event: SocketEvent) => void,
	onError?: (error: Event) => void,
	onClose?: () => void
): WebSocket {
	const ws = new WebSocket(url);

	ws.onopen = () => {
		console.log('WebSocket connected', url);
	};

	ws.onmessage = (message) => {
		const event = JSON.parse(message.data) as SocketEvent;
		onEvent(event);
	};

	ws.onerror = (error) => {
		console.error('WebSocket error:', url, error);
		onError?.(error);
	};

	ws.onclose = (event) => {
		// code 1008 = policy violation (backend rejected the Origin); 1006 = abnormal
		// close, usually the connection never reached the server (refused / blocked).
		console.log('WebSocket disconnected', url, 'code=', event.code, 'reason=', event.reason);
		onClose?.();
	};

	return ws;
}

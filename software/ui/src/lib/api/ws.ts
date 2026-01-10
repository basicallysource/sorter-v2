import type { SocketEvent } from './events';

export function connectWebSocket(
	url: string,
	onEvent: (event: SocketEvent) => void,
	onError?: (error: Event) => void,
	onClose?: () => void
): WebSocket {
	const ws = new WebSocket(url);

	ws.onopen = () => {
		console.log('WebSocket connected');
	};

	ws.onmessage = (message) => {
		const event = JSON.parse(message.data) as SocketEvent;
		onEvent(event);
	};

	ws.onerror = (error) => {
		console.error('WebSocket error:', error);
		onError?.(error);
	};

	ws.onclose = () => {
		console.log('WebSocket disconnected');
		onClose?.();
	};

	return ws;
}

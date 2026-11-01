import { createClient } from '@connectrpc/connect';
import { createConnectTransport } from '@connectrpc/connect-web';
import { AdminService, TestPrintService } from '$lib/gen/testprints/v1/testprints_pb';

const TRANSPORT = createConnectTransport({ baseUrl: '/rpc', defaultTimeoutMs: 20000 });
export const tests = createClient(TestPrintService, TRANSPORT);
export const admin = createClient(AdminService, TRANSPORT);

export function requestID() {
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	let timestamp = BigInt(Date.now());
	for (let i = 5; i >= 0; i--) { bytes[i] = Number(timestamp & 255n); timestamp >>= 8n; }
	bytes[6] = (bytes[6] & 15) | 112;
	bytes[8] = (bytes[8] & 63) | 128;
	const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

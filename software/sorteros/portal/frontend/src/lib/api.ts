export type WifiNetwork = {
	ssid: string;
	signal: number;
	security: string;
	in_use: boolean;
};

export type StatusResponse = {
	mode: 'ap' | 'mock';
	hostname: string;
	suggested_url: string;
	configured: boolean;
	last_attempt: {
		ssid: string;
		hostname: string | null;
		result: string;
		error?: string;
	} | null;
};

export type ScanResponse = {
	networks: WifiNetwork[];
	mocked: boolean;
};

export type ConnectPayload = {
	ssid: string;
	password?: string;
	hidden?: boolean;
	hostname?: string | null;
	sshKey?: string | null;
	rendezvousId?: string | null;
	publicKey?: string | null;
};

export type ConnectResponse = {
	ok: true;
	next_url: string;
	hostname: string;
	teardown_in_s?: number;
	mocked: boolean;
};

async function jsonOrThrow(res: Response): Promise<any> {
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const body = await res.json();
			detail = body?.detail ?? detail;
		} catch {
			// ignore non-JSON error bodies
		}
		throw new Error(detail);
	}
	return res.json();
}

export async function fetchStatus(): Promise<StatusResponse> {
	return jsonOrThrow(await fetch('/api/status'));
}

export async function scanNetworks(rescan = true): Promise<ScanResponse> {
	return jsonOrThrow(await fetch(`/api/wifi-scan?rescan=${rescan ? 'true' : 'false'}`));
}

export async function connect(payload: ConnectPayload): Promise<ConnectResponse> {
	return jsonOrThrow(
		await fetch('/api/wifi-connect', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		})
	);
}

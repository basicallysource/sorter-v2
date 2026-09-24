import type { MachineNetwork, MachineNetworkInfo } from './api';

/** A Sorter reports its networks on every heartbeat (every 30 s), so a report
 * older than this means it went offline or stopped reporting. */
const CURRENT_MS = 5 * 60 * 1000;

const KIND_ORDER: Record<MachineNetwork['kind'], number> = {
	wifi: 0,
	ethernet: 1,
	other: 2,
	tailscale: 3
};

function internetOrder(internet: boolean | null): number {
	return internet === true ? 0 : internet === null ? 1 : 2;
}

/** `http://host/`, with `:port` unless it is 80. null when the Sorter did not
 * say which port its UI is on: no link beats a wrong one. */
export function sorterUrl(host: string, port: number | null): string | null {
	if (port == null) return null;
	const urlHost = host.includes(':') ? `[${host}]` : host;
	return `http://${urlHost}${port === 80 ? '' : `:${port}`}/`;
}

/** The networks around the Sorter, best first: one that reaches the internet,
 * then Wi-Fi before Ethernet. Never Tailscale. */
export function lanNetworks(info: MachineNetworkInfo): MachineNetwork[] {
	return info.networks
		.filter((network) => network.kind !== 'tailscale')
		.sort(
			(a, b) =>
				internetOrder(a.internet) - internetOrder(b.internet) || KIND_ORDER[a.kind] - KIND_ORDER[b.kind]
		);
}

export function tailnetNetworks(info: MachineNetworkInfo): MachineNetwork[] {
	return info.networks.filter((network) => network.kind === 'tailscale');
}

/** The one link that opens the Sorter's UI: its best LAN address. */
export function localUiUrl(info: MachineNetworkInfo | null): string | null {
	if (!info) return null;
	const best = lanNetworks(info)[0];
	return best ? sorterUrl(best.address, info.ports.ui) : null;
}

/** "on Wi-Fi HomeNet", "on Ethernet", "from anywhere on your tailnet". */
export function networkLabel(network: MachineNetwork): string {
	switch (network.kind) {
		case 'wifi':
			return network.name ? `on Wi-Fi ${network.name}` : 'on Wi-Fi';
		case 'ethernet':
			return 'on Ethernet';
		case 'tailscale':
			return 'from anywhere on your tailnet';
		default:
			return `on ${network.name ?? network.iface ?? 'another network'}`;
	}
}

/** Whether a report is recent enough to be where the Sorter is now. */
export function isCurrentReport(reportedAt: string | null): boolean {
	if (!reportedAt) return false;
	const then = new Date(reportedAt).getTime();
	return Number.isFinite(then) && Date.now() - then < CURRENT_MS;
}

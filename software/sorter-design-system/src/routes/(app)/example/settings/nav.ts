// The Sorter UI's settings pages, as its side nav lists them.
import Settings from '@lucide/svelte/icons/settings';
import Cloud from '@lucide/svelte/icons/cloud';
import Cpu from '@lucide/svelte/icons/cpu';
import Network from '@lucide/svelte/icons/network';
import GitBranch from '@lucide/svelte/icons/git-branch';
import Wrench from '@lucide/svelte/icons/wrench';
import Camera from '@lucide/svelte/icons/camera';
import Layers from '@lucide/svelte/icons/layers';
import CircuitBoard from '@lucide/svelte/icons/circuit-board';
import ShieldAlert from '@lucide/svelte/icons/shield-alert';
import Zap from '@lucide/svelte/icons/zap';
import AudioWaveform from '@lucide/svelte/icons/audio-waveform';
import Gauge from '@lucide/svelte/icons/gauge';

const base = '/example/settings';

type Page = { href: string; label: string };
// A page of the side nav; its sub-tabs, if it has any, are listed under it.
type NavPage = Page & { icon: typeof Settings; children?: Page[] };
type NavGroup = { label?: string; items: NavPage[] };

export const settingsGroups: NavGroup[] = [
	{
		items: [
			{ href: base, label: 'General', icon: Settings },
			{ href: `${base}/hive`, label: 'Hive', icon: Cloud },
			{ href: `${base}/local-models`, label: 'Local models', icon: Cpu },
			{ href: `${base}/providers`, label: 'Providers', icon: Network },
			{ href: `${base}/versions`, label: 'Versions', icon: GitBranch }
		]
	},
	{
		label: 'Hardware',
		items: [
			{ href: `${base}/c-channel-1`, label: 'C-Channel 1', icon: Wrench },
			{ href: `${base}/c-channel-2`, label: 'C-Channel 2', icon: Camera },
			{ href: `${base}/c-channel-3`, label: 'C-Channel 3', icon: Camera },
			{
				href: `${base}/c-channel-4`,
				label: 'Classification channel',
				icon: Camera,
				children: [{ href: `${base}/c-channel-4-stallguard`, label: 'StallGuard' }]
			},
			{
				href: `${base}/chute`,
				label: 'Chute',
				icon: Wrench,
				children: [
					{ href: `${base}/chute-aiming`, label: 'Chute aiming' },
					{ href: `${base}/chute-stallguard`, label: 'StallGuard' }
				]
			},
			{ href: `${base}/storage-layers`, label: 'Storage layers', icon: Layers },
			{ href: `${base}/control-board`, label: 'Control board', icon: CircuitBoard }
		]
	},
	{
		label: 'Helpers',
		items: [
			{ href: `${base}/incidents`, label: 'Incidents', icon: ShieldAlert },
			{ href: `${base}/power-stress`, label: 'Power stress test', icon: Zap },
			{ href: `${base}/jitter`, label: 'Jitter test', icon: AudioWaveform },
			{ href: `${base}/performance`, label: 'Performance', icon: Gauge }
		]
	}
];

// The channel pages whose main thing is a camera: they take the whole width.
export const cameraSections = ['c-channel-2', 'c-channel-3', 'c-channel-4'];

// Every page the side nav lists, sub-tabs after their item.
export const settingsPages = settingsGroups.flatMap((g) =>
	g.items.flatMap((i) => [i, ...(i.children ?? [])])
);

export function labelFor(section: string): string | undefined {
	return settingsPages.find((i) => i.href === `${base}/${section}`)?.label;
}

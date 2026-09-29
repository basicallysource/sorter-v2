// The site's pages, in the side nav's order.
import Compass from '@lucide/svelte/icons/compass';
import ListChecks from '@lucide/svelte/icons/list-checks';
import Layers from '@lucide/svelte/icons/layers';
import Gauge from '@lucide/svelte/icons/gauge';
import Settings from '@lucide/svelte/icons/settings';

export const groups = [
	{
		items: [
			{ href: '/', label: 'Overview', icon: Compass },
			{ href: '/rules', label: 'Rules', icon: ListChecks }
		]
	},
	{
		label: 'Foundations',
		items: [{ href: '/surfaces', label: 'Surfaces', icon: Layers }]
	},
	{
		label: 'Example app',
		items: [
			{ href: '/example', label: 'Dashboard', icon: Gauge },
			{ href: '/example/settings', label: 'Settings', icon: Settings }
		]
	}
];

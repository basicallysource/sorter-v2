// The site's pages, in the side nav's order.
import Compass from '@lucide/svelte/icons/compass';
import ListChecks from '@lucide/svelte/icons/list-checks';
import Layers from '@lucide/svelte/icons/layers';
import Palette from '@lucide/svelte/icons/palette';
import Type from '@lucide/svelte/icons/type';
import Shapes from '@lucide/svelte/icons/shapes';
import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';
import MousePointerClick from '@lucide/svelte/icons/mouse-pointer-click';
import TextCursorInput from '@lucide/svelte/icons/text-cursor-input';
import AppWindow from '@lucide/svelte/icons/app-window';
import MessageSquareWarning from '@lucide/svelte/icons/message-square-warning';
import Hourglass from '@lucide/svelte/icons/hourglass';
import Signpost from '@lucide/svelte/icons/signpost';
import Table from '@lucide/svelte/icons/table';
import Boxes from '@lucide/svelte/icons/boxes';
import Gauge from '@lucide/svelte/icons/gauge';
import Settings from '@lucide/svelte/icons/settings';
import BookOpen from '@lucide/svelte/icons/book-open';

export const groups = [
	{
		items: [
			{ href: '/', label: 'Overview', icon: Compass },
			{ href: '/rules', label: 'Rules', icon: ListChecks }
		]
	},
	{
		label: 'Foundations',
		items: [
			{ href: '/surfaces', label: 'Surfaces', icon: Layers },
			{ href: '/color', label: 'Color', icon: Palette },
			{ href: '/type', label: 'Type', icon: Type },
			{ href: '/icons', label: 'Icons', icon: Shapes },
			{ href: '/layout', label: 'Layout', icon: LayoutDashboard }
		]
	},
	{
		label: 'Components',
		items: [
			{ href: '/buttons', label: 'Buttons', icon: MousePointerClick },
			{ href: '/forms', label: 'Forms', icon: TextCursorInput },
			{ href: '/overlays', label: 'Overlays', icon: AppWindow },
			{ href: '/notices', label: 'Notices', icon: MessageSquareWarning },
			{ href: '/loading', label: 'Loading', icon: Hourglass },
			{ href: '/navigation', label: 'Navigation', icon: Signpost },
			{ href: '/data', label: 'Data', icon: Table },
			{ href: '/profiles', label: 'Profiles', icon: Boxes }
		]
	},
	{
		label: 'Example app',
		items: [
			{ href: '/example', label: 'Dashboard', icon: Gauge },
			{ href: '/example/settings', label: 'Settings', icon: Settings }
		]
	},
	{
		label: 'Written',
		items: [{ href: '/docs', label: 'Docs', icon: BookOpen }]
	}
];

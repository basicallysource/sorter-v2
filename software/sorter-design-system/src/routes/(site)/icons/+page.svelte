<script lang="ts">
	import type { Component } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Plus from '@lucide/svelte/icons/plus';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash from '@lucide/svelte/icons/trash-2';
	import Copy from '@lucide/svelte/icons/copy';
	import Download from '@lucide/svelte/icons/download';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Settings from '@lucide/svelte/icons/settings';
	import House from '@lucide/svelte/icons/house';
	import Power from '@lucide/svelte/icons/power';
	import PowerOff from '@lucide/svelte/icons/power-off';
	import Pause from '@lucide/svelte/icons/pause';
	import Play from '@lucide/svelte/icons/play';
	import Square from '@lucide/svelte/icons/square';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import Check from '@lucide/svelte/icons/check';
	import Info from '@lucide/svelte/icons/info';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import OctagonAlert from '@lucide/svelte/icons/octagon-alert';
	import Camera from '@lucide/svelte/icons/camera';
	import Cloud from '@lucide/svelte/icons/cloud';
	import Layers from '@lucide/svelte/icons/layers';
	import Search from '@lucide/svelte/icons/search';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import Plug from '@lucide/svelte/icons/plug';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import GitFork from '@lucide/svelte/icons/git-fork';
	import Upload from '@lucide/svelte/icons/upload';
	import Globe from '@lucide/svelte/icons/globe';
	import Save from '@lucide/svelte/icons/save';
	import BookmarkPlus from '@lucide/svelte/icons/bookmark-plus';
	import Replace from '@lucide/svelte/icons/replace';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import ToggleRight from '@lucide/svelte/icons/toggle-right';
	import ToggleLeft from '@lucide/svelte/icons/toggle-left';
	import KeyRound from '@lucide/svelte/icons/key-round';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Send from '@lucide/svelte/icons/send';
	import Boxes from '@lucide/svelte/icons/boxes';
	import Funnel from '@lucide/svelte/icons/funnel';
	import ImageIcon from '@lucide/svelte/icons/image';
	import CornerDownRight from '@lucide/svelte/icons/corner-down-right';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Button from '$lib/components/Button.svelte';

	type Icon = Component<{ size?: number; class?: string }>;
	const meanings: { icon: Icon; name: string; means: string }[] = [
		{ icon: X, name: 'x', means: 'Close' },
		{ icon: Plus, name: 'plus', means: 'Add, new' },
		{ icon: Pencil, name: 'pencil', means: 'Rename, edit' },
		{ icon: Trash, name: 'trash-2', means: 'Delete' },
		{ icon: Copy, name: 'copy', means: 'Duplicate, copy' },
		{ icon: GitFork, name: 'git-fork', means: 'Fork: a profile of your own from one' },
		{ icon: Download, name: 'download', means: 'Download a file' },
		{ icon: Upload, name: 'upload', means: 'Upload a file or a picture' },
		{ icon: Globe, name: 'globe', means: 'Publish, public' },
		{ icon: Save, name: 'save', means: 'Save' },
		{ icon: BookmarkPlus, name: 'bookmark-plus', means: 'Save to your library' },
		{ icon: Replace, name: 'replace', means: 'Swap for another' },
		{ icon: ArrowUp, name: 'arrow-up', means: 'Move up in a list' },
		{ icon: ArrowDown, name: 'arrow-down', means: 'Move down in a list' },
		{ icon: GripVertical, name: 'grip-vertical', means: 'Drag to reorder' },
		{ icon: ToggleRight, name: 'toggle-right', means: 'Turn on' },
		{ icon: ToggleLeft, name: 'toggle-left', means: 'Turn off' },
		{ icon: RefreshCw, name: 'refresh-cw', means: 'Rescan, reload (never spun)' },
		{ icon: Settings, name: 'settings', means: 'Settings' },
		{ icon: House, name: 'house', means: 'Home the machine' },
		{ icon: Power, name: 'power', means: 'Start the hardware' },
		{ icon: PowerOff, name: 'power-off', means: 'Power the machine down' },
		{ icon: Play, name: 'play', means: 'Start sorting' },
		{ icon: Pause, name: 'pause', means: 'Pause' },
		{ icon: Square, name: 'square', means: 'Stop a motor' },
		{ icon: RotateCw, name: 'rotate-cw', means: 'Rotate a camera' },
		{ icon: Crosshair, name: 'crosshair', means: 'Aim, calibrate a position' },
		{ icon: Camera, name: 'camera', means: 'A camera, a feed' },
		{ icon: Layers, name: 'layers', means: 'Storage layers' },
		{ icon: Cloud, name: 'cloud', means: 'Hive' },
		{ icon: Plug, name: 'plug', means: 'Connect' },
		{ icon: KeyRound, name: 'key-round', means: 'An API key, a token' },
		{ icon: Sparkles, name: 'sparkles', means: 'AI, an assistant' },
		{ icon: Send, name: 'send', means: 'Send a message' },
		{ icon: Boxes, name: 'boxes', means: 'A kit' },
		{ icon: Funnel, name: 'funnel', means: "A profile's rules, a filter" },
		{ icon: ImageIcon, name: 'image', means: 'A picture' },
		{ icon: CornerDownRight, name: 'corner-down-right', means: 'Where a piece goes' },
		{ icon: Search, name: 'search', means: 'Search' },
		{ icon: ChevronDown, name: 'chevron-down', means: 'Opens a list below' },
		{ icon: ChevronRight, name: 'chevron-right', means: 'Opens a section, jogs clockwise' },
		{ icon: ChevronLeft, name: 'chevron-left', means: 'Jogs counterclockwise' },
		{ icon: ArrowLeft, name: 'arrow-left', means: 'Back to where you were' },
		{ icon: ArrowRight, name: 'arrow-right', means: 'Goes somewhere else' },
		{ icon: ArrowUpRight, name: 'arrow-up-right', means: 'Leaves the app, or opens a new tab' },
		{ icon: Ellipsis, name: 'ellipsis', means: 'A button that opens a menu (three dots)' },
		{ icon: Check, name: 'check', means: 'Chosen, done, yes' },
		{ icon: Sun, name: 'sun', means: 'Light mode' },
		{ icon: Moon, name: 'moon', means: 'Dark mode' },
		{ icon: Info, name: 'info', means: 'An info notice' },
		{ icon: CircleCheck, name: 'circle-check', means: 'A success notice' },
		{ icon: TriangleAlert, name: 'triangle-alert', means: 'A warning notice' },
		{ icon: OctagonAlert, name: 'octagon-alert', means: 'A danger notice, a fault' }
	];
</script>

<svelte:head><title>Icons · Sorter design system</title></svelte:head>

<PageHeader
	title="Icons"
	lead="Lucide and only Lucide, with square caps and mitred joins like every other edge here. An icon backs up a word; alone, it carries a name."
	doc="icons"
/>

<SiteSection
	title="Sizes"
	lead="16 in text and controls, the default. 14 in a small button or beside 12px text, 18 in a notice, 24 alone in an empty state. Nothing larger."
>
	<Specimen
		code={`import Camera from '@lucide/svelte/icons/camera';

<Camera size={16} />`}
	>
		<div class="flex flex-wrap items-end gap-8 text-ink">
			{#each [14, 16, 18, 24] as size (size)}
				<div class="flex flex-col items-center gap-2">
					<Camera {size} />
					<span class="num text-xs text-ink-muted">{size}</span>
				</div>
			{/each}
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="What is what"
	lead="One icon per meaning, across both apps. A new meaning gets a row here before it gets an icon."
>
	<div class="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
		{#each meanings as m (m.name)}
			<div class="flex items-center gap-3 bg-surface px-4 py-3">
				<m.icon size={16} class="shrink-0 text-ink" />
				<div class="min-w-0">
					<div class="truncate text-sm text-ink">{m.means}</div>
					<code class="font-mono text-xs text-ink-muted">{m.name}</code>
				</div>
			</div>
		{/each}
	</div>
</SiteSection>

<SiteSection
	title="With words"
	lead="An icon leads its label. An icon alone is an icon button with a name, which the pointer shows."
>
	<Specimen>
		<div class="flex flex-wrap items-center gap-3">
			<Button icon={Plus}>Add bin</Button>
			<Button variant="ghost" icon={ArrowUpRight}>Open Hive</Button>
			<Button variant="ghost" icon={Pencil} label="Rename profile" />
		</div>
	</Specimen>
</SiteSection>

<SiteSection title="Rules">
	<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface text-sm">
		<li class="px-5 py-3">
			<span class="font-medium text-ink">Import one icon at a time,</span>
			<span class="font-mono text-ink-muted">@lucide/svelte/icons/&lt;name&gt;</span><span
				class="text-ink-muted">, never the whole set.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">Never draw one.</span>
			<span class="text-ink-muted"
				>No hand-written SVG paths in a component: they sit at a different weight and nobody can
				review them. If Lucide has nothing, use a word.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">An icon is text.</span>
			<span class="text-ink-muted"
				>It takes the color of the words beside it, and never a color of its own, except a notice's
				icon in its tone.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">A button that opens a menu is three dots,</span>
			<span class="text-ink-muted"
				>never the icon of one of the actions inside it. The machine's menu opens from three dots; a
				power icon would say the button powers something off.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">Nothing spins.</span>
			<span class="text-ink-muted"
				>A refresh icon stays still while its button shows the Spinner.</span
			>
		</li>
	</ul>
</SiteSection>

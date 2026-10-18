<script lang="ts">
	import Settings from '@lucide/svelte/icons/settings';
	import Cloud from '@lucide/svelte/icons/cloud';
	import Wrench from '@lucide/svelte/icons/wrench';
	import Camera from '@lucide/svelte/icons/camera';
	import Layers from '@lucide/svelte/icons/layers';
	import { page } from '$app/state';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import SideNav from '$lib/components/SideNav.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import Pager from '$lib/components/Pager.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import Input from '$lib/components/Input.svelte';
	import Badge from '$lib/components/Badge.svelte';

	let tab = $state<'bins' | 'layers' | 'discard'>('bins');

	// The views of a page with an address each: tabs that are links, and the
	// same list in the top bar. Here the addresses are this page's hashes.
	const views = [
		{ value: 'overview', label: 'Overview', href: '/navigation#overview' },
		{ value: 'runs', label: 'Runs', href: '/navigation#runs' },
		{ value: 'pieces', label: 'Pieces', href: '/navigation#pieces' },
		{ value: 'incidents', label: 'Incidents', href: '/navigation#incidents' }
	];
	const view = $derived(page.url.hash.slice(1) || 'overview');

	const pages = [
		{ href: '/navigation', label: 'Dashboard' },
		{ href: '/navigation#bins', label: 'Bins' },
		{ href: '/navigation#profiles', label: 'Profiles' },
		{ href: '/navigation#records', label: 'Records' },
		{ href: '/navigation#settings', label: 'Settings' }
	];

	// A page with views lists them as children: its name stays a link to the
	// first, and a chevron opens the rest. (A real app's views are paths, and
	// the page is current on all of them; here Records stands in for this page.)
	const pagesWithViews = pages.map((p) =>
		p.label === 'Dashboard'
			? { ...p, href: '/' }
			: p.label === 'Records'
				? {
						...p,
						href: '/navigation',
						children: views.map((v) => ({ href: v.href, label: v.label }))
					}
				: p
	);

	const PAGE_SIZE = 50;
	const TOTAL = 36652;
	let listPage = $state(3);
	const listPages = Math.ceil(TOTAL / PAGE_SIZE);
</script>

<svelte:head><title>Navigation · Sorter design system</title></svelte:head>

<PageHeader
	title="Navigation"
	lead="Three levels: the top bar for the app's pages, the side nav for a page's sections, tabs for views of one thing. A disclosure hides what most people never need."
	doc="layout"
/>

<SiteSection
	title="Top bar"
	lead="The mark, the app's pages, and on the right what applies everywhere: the machine and its status. The current page's mark sits on the bar's own line, in its place. Light or dark is a setting, never a switch here."
>
	<div class="rounded-panel bg-surface p-2">
		<div class="overflow-hidden rounded-control bg-canvas">
			<TopBar sticky={false} items={pages}>
				{#snippet brand()}<Wordmark href="/navigation" />{/snippet}
				{#snippet end()}<Badge tone="success" dot>Running</Badge>{/snippet}
			</TopBar>
			<div class="h-16"></div>
		</div>
	</div>
	<p class="max-w-2xl text-sm text-ink-muted">
		Where the pages and the right side no longer fit side by side, the pages fold into one menu, its
		button named for the page you are on. The bar folds by its own width, so here it is at a phone's
		390px. <code class="font-mono text-ink">collapse</code> sets the point: 768px by default, wider for
		more pages.
	</p>
	<div class="w-full max-w-[24.375rem] rounded-panel bg-surface p-2">
		<div class="overflow-hidden rounded-control bg-canvas">
			<TopBar sticky={false} items={pages}>
				{#snippet brand()}<Wordmark href="/navigation" />{/snippet}
				{#snippet end()}<Badge tone="success" dot>Running</Badge>{/snippet}
			</TopBar>
			<div class="h-16"></div>
		</div>
	</div>
</SiteSection>

<SiteSection
	title="A page with views"
	lead="Records has an Overview, its Runs, its Pieces and its Incidents. They are the page's tabs, each a link with an address of its own, and the top bar's Records item lists them too: its name stays a link to the first, and the chevron beside it opens a menu of the views (the one you are on is checked). One list feeds both."
>
	<div class="rounded-panel bg-surface p-2">
		<div class="overflow-hidden rounded-control bg-canvas">
			<TopBar sticky={false} items={pagesWithViews}>
				{#snippet brand()}<Wordmark href="/navigation" />{/snippet}
				{#snippet end()}<Badge tone="success" dot>Running</Badge>{/snippet}
			</TopBar>
			<div class="px-6 pt-4">
				<Tabs label="Records" value={view} items={views} />
			</div>
			<div class="h-16"></div>
		</div>
	</div>
	<p class="max-w-2xl text-sm text-ink-muted">
		Folded, the page is a group in the pages menu with its views under its name.
	</p>
	<div class="w-full max-w-[24.375rem] rounded-panel bg-surface p-2">
		<div class="overflow-hidden rounded-control bg-canvas">
			<TopBar sticky={false} items={pagesWithViews}>
				{#snippet brand()}<Wordmark href="/navigation" />{/snippet}
				{#snippet end()}<Badge tone="success" dot>Running</Badge>{/snippet}
			</TopBar>
			<div class="h-16"></div>
		</div>
	</div>
</SiteSection>

<SiteSection
	title="Side nav"
	lead="A column on the surface plane, the full height beside the content, which sits on the canvas: no line between them, because their fills differ. The current section takes the primary's tint. A section with pages of its own lists them indented under it, always: the chute's aiming and its StallGuard are sub-tabs of the chute, which is the first view of them. A sub-tab has no icon and its name lines up with its section's."
>
	<Specimen>
		<div class="w-60">
			<SideNav
				label="Settings"
				groups={[
					{
						items: [
							{ href: '/navigation#general', label: 'General', icon: Settings },
							{ href: '/navigation#hive', label: 'Hive', icon: Cloud }
						]
					},
					{
						label: 'Hardware',
						items: [
							{ href: '/navigation#c1', label: 'C-Channel 1', icon: Wrench },
							{ href: '/navigation#c2', label: 'C-Channel 2', icon: Camera },
							{
								href: '/navigation#chute',
								label: 'Chute',
								icon: Wrench,
								children: [
									{ href: '/navigation#chute-aiming', label: 'Chute aiming' },
									{ href: '/navigation', label: 'StallGuard' }
								]
							},
							{ href: '/navigation#layers', label: 'Storage layers', icon: Layers, meta: '3' }
						]
					}
				]}
			/>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Tabs"
	lead="Views of one thing, in a page or at the top of a flush panel. The chosen tab's mark replaces the bar's line under it. Arrow keys move between tabs."
>
	<Panel flush>
		<Tabs
			label="Bins"
			inset
			bind:value={tab}
			items={[
				{ value: 'bins', label: 'Bins', count: 36 },
				{ value: 'layers', label: 'Layers', count: 3 },
				{ value: 'discard', label: 'Discard' }
			]}
		/>
		<p class="px-5 py-4 text-sm text-ink-muted">
			{#if tab === 'bins'}36 bins across 3 layers.{:else if tab === 'layers'}3 layers, 12 bins each.{:else}Parts
				the profile has no bin for.{/if}
		</p>
	</Panel>
</SiteSection>

<SiteSection
	title="Pager"
	lead="Where you are in a long list: which of how many are shown, the first, previous, next and last page, and the page's number to type. One above the list and one under it, so the end of a long page is not a scroll back to the top. It holds no data; the app asks for another page."
>
	<Specimen
		code={`<Pager label="Pieces" page={3} pages={734} from={101} to={150} total={36652}
	noun="pieces" onpage={go} />`}
	>
		<div class="w-full">
			<Pager
				label="Pieces"
				page={listPage}
				pages={listPages}
				from={(listPage - 1) * PAGE_SIZE + 1}
				to={Math.min(listPage * PAGE_SIZE, TOTAL)}
				total={TOTAL}
				noun="pieces"
				onpage={(n) => (listPage = n)}
			/>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Disclosure"
	lead="Settings most people never touch, closed until asked for. It sits in a divided list like any row."
>
	<Panel title="C-Channel 1" flush>
		<div class="divide-y divide-line">
			<SettingRow label="Speed" help="Steps a second at the motor." for="nav-speed">
				<Input id="nav-speed" type="number" value={800} unit="steps/s" class="w-36" />
			</SettingRow>
			<Disclosure title="Driver settings" help="Current, microsteps">
				<div class="divide-y divide-line pl-6">
					<SettingRow label="Run current" for="nav-current">
						<Input id="nav-current" type="number" value={900} unit="mA" class="w-28" />
					</SettingRow>
				</div>
			</Disclosure>
		</div>
	</Panel>
</SiteSection>

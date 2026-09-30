<script lang="ts">
	import Settings from '@lucide/svelte/icons/settings';
	import Cloud from '@lucide/svelte/icons/cloud';
	import Wrench from '@lucide/svelte/icons/wrench';
	import Camera from '@lucide/svelte/icons/camera';
	import Layers from '@lucide/svelte/icons/layers';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import SideNav from '$lib/components/SideNav.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import Input from '$lib/components/Input.svelte';
	import Badge from '$lib/components/Badge.svelte';

	let tab = $state<'bins' | 'layers' | 'discard'>('bins');

	const pages = [
		{ href: '/navigation', label: 'Dashboard' },
		{ href: '/navigation#bins', label: 'Bins' },
		{ href: '/navigation#profiles', label: 'Profiles' },
		{ href: '/navigation#records', label: 'Records' },
		{ href: '/navigation#settings', label: 'Settings' }
	];
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
	title="Side nav"
	lead="A column on the surface plane, the full height beside the content, which sits on the canvas: no line between them, because their fills differ. The current section takes the primary's tint."
>
	<Specimen>
		<div class="w-60">
			<SideNav
				label="Settings"
				groups={[
					{
						items: [
							{ href: '/navigation', label: 'General', icon: Settings },
							{ href: '/navigation#hive', label: 'Hive', icon: Cloud }
						]
					},
					{
						label: 'Hardware',
						items: [
							{ href: '/navigation#c1', label: 'C-Channel 1', icon: Wrench },
							{ href: '/navigation#c2', label: 'C-Channel 2', icon: Camera },
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

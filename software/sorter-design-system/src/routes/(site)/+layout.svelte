<!--
	The site's shell: the top bar, a side nav on the surface plane the full
	height of the window, and the pages on the canvas beside it. The site's
	own viewing controls (mode and primary) sit at the foot of the side nav:
	in an app those are settings, and nothing puts them in a top bar.
-->
<script lang="ts">
	import MenuIcon from '@lucide/svelte/icons/menu';
	import TopBar from '$lib/components/TopBar.svelte';
	import SideNav from '$lib/components/SideNav.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import Button from '$lib/components/Button.svelte';
	import ThemeControls from '$lib/site/ThemeControls.svelte';
	import { groups } from '$lib/site/pages';
	import { afterNavigate } from '$app/navigation';

	let { children } = $props();
	let menuOpen = $state(false);
	afterNavigate(() => (menuOpen = false));
</script>

<TopBar items={[]}>
	{#snippet brand()}
		<div class="flex items-center gap-3">
			<Wordmark />
			<span class="hidden text-sm text-ink-muted sm:inline">Design system</span>
		</div>
	{/snippet}
	{#snippet end()}
		<div class="lg:hidden">
			<Popover label="Pages" placement="bottom-end" width="16rem" bind:open={menuOpen}>
				{#snippet trigger(props)}
					<Button {...props} variant="ghost" size="sm" icon={MenuIcon} label="Pages" />
				{/snippet}
				<SideNav {groups} label="Design system" />
				<div class="mt-6"><ThemeControls /></div>
			</Popover>
		</div>
	{/snippet}
</TopBar>

<div class="flex">
	<aside
		class="sticky top-(--size-topbar) hidden h-[calc(100dvh-var(--size-topbar))] w-60 shrink-0 flex-col gap-8 overflow-y-auto bg-surface px-3 py-6 lg:flex"
	>
		<SideNav {groups} label="Design system" />
		<div class="mt-auto"><ThemeControls /></div>
	</aside>
	<main class="min-w-0 flex-1 px-4 pt-8 pb-24 sm:px-8">
		<div class="mx-auto max-w-5xl">
			{@render children()}
		</div>
	</main>
</div>

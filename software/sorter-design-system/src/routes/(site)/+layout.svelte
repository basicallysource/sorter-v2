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
		<ThemeControls />
		<div class="lg:hidden">
			<Popover label="Pages" placement="bottom-end" width="16rem" bind:open={menuOpen}>
				{#snippet trigger(props)}
					<Button {...props} variant="ghost" size="sm" icon={MenuIcon} label="Pages" />
				{/snippet}
				<SideNav {groups} label="Design system" />
			</Popover>
		</div>
	{/snippet}
</TopBar>

<div class="mx-auto flex max-w-[1360px] gap-10 px-4 sm:px-6">
	<aside
		class="sticky top-12 hidden h-[calc(100dvh-3rem)] w-52 shrink-0 overflow-y-auto py-8 lg:block"
	>
		<SideNav {groups} label="Design system" />
	</aside>
	<main class="min-w-0 flex-1 pt-8 pb-24">
		{@render children()}
	</main>
</div>

<!--
	The example app: the Sorter UI's shell as it should be built. From lg up
	the screen is exactly the window: the top bar, and under it an area that
	fills the rest, so the page never scrolls; what can grow scrolls inside
	its own panel or column (docs/layout.md). On a phone it is one column
	that scrolls, and the top bar folds its pages into one menu. Light or
	dark is under Settings > General, not in the top bar.
-->
<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import TopBar from '$lib/components/TopBar.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import Button from '$lib/components/Button.svelte';
	import Select from '$lib/components/Select.svelte';

	let { children } = $props();
	let profile = $state('september');
</script>

<div class="flex min-h-dvh flex-col lg:h-dvh">
	<TopBar
		sticky={false}
		items={[
			{ href: '/example', label: 'Dashboard' },
			{ href: '/example/settings', label: 'Settings' }
		]}
	>
		{#snippet brand()}<Wordmark href="/example" />{/snippet}
		{#snippet end()}
			<div class="hidden items-center gap-3 md:flex">
				<span class="flex items-center gap-2 text-sm text-ink">
					<span class="size-2 rounded-full bg-success" aria-hidden="true"></span>
					Bench sorter
				</span>
				<Select
					label="Sorting profile"
					size="sm"
					class="w-44"
					bind:value={profile}
					options={[
						{ value: 'september', label: 'September' },
						{ value: 'bulk', label: 'Bulk by color' },
						{ value: 'technic', label: 'Technic parts' }
					]}
				/>
			</div>
			<Button href="/" size="sm" variant="ghost" icon={ArrowLeft}>
				<span class="max-sm:sr-only">Design system</span>
			</Button>
		{/snippet}
	</TopBar>
	<div class="flex min-h-0 flex-1 flex-col">
		{@render children()}
	</div>
</div>

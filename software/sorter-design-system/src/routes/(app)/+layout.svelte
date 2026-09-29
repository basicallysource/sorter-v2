<!--
	The example app: the Sorter UI's shell as it should be built. The top
	bar owns the one line on the page; everything under it is canvas and
	panels.
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

<TopBar
	items={[
		{ href: '/example', label: 'Dashboard' },
		{ href: '/example/settings', label: 'Settings' }
	]}
>
	{#snippet brand()}<Wordmark href="/example" />{/snippet}
	{#snippet end()}
		<div class="hidden items-center gap-2 md:flex">
			<span class="flex items-center gap-2 px-2 text-sm text-ink">
				<span class="size-2 rounded-full bg-success" aria-hidden="true"></span>
				Bench sorter
			</span>
			<Select
				size="sm"
				bind:value={profile}
				options={[
					{ value: 'september', label: 'September' },
					{ value: 'bulk', label: 'Bulk by color' }
				]}
				class="w-36"
			/>
		</div>
		<Button href="/" size="sm" variant="ghost" icon={ArrowLeft}>
			<span class="max-sm:sr-only">Design system</span>
		</Button>
	{/snippet}
</TopBar>

{@render children()}

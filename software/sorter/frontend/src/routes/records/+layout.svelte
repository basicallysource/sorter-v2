<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import AppShell from '$lib/components/AppShell.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import { scrollerOf } from '$lib/records/scroll';
	import { recordsViewAt, recordsViews } from '$lib/records/tabs';

	let { children } = $props();

	const view = $derived(recordsViewAt(page.url.pathname));
	let column = $state<HTMLElement | null>(null);

	// Another view starts at its top. (Back and Forward put a page where it was,
	// and paging within a view brings its own list into sight.)
	afterNavigate(({ type, from, to }) => {
		if (type === 'popstate' || from?.url.pathname === to?.url.pathname) return;
		scrollerOf(column)?.scrollTo({ top: 0 });
	});
</script>

<svelte:head>
	<title>Records - Sorter</title>
</svelte:head>

<!-- The page's views are its tabs, each a link with an address of its own, and
	the top bar's Records menu (AppHeader) lists the same ones. -->
<AppShell>
	<div
		bind:this={column}
		class="mx-auto flex w-full max-w-[1500px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6"
	>
		<PageHeader
			title="Records"
			description="Sorting history for this machine: every piece seen across all saved runs."
		/>
		<Tabs label="Records" value={view} items={recordsViews} />
		{@render children()}
	</div>
</AppShell>

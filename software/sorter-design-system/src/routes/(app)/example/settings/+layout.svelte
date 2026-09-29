<!--
	Settings: the side nav on the canvas, the page's panels beside it. On a
	narrow screen the nav becomes a select above the content.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import SideNav from '$lib/components/SideNav.svelte';
	import Select from '$lib/components/Select.svelte';
	import { settingsGroups } from './nav';

	let { children } = $props();

	const items = settingsGroups.flatMap((g) => g.items);
	const here = $derived(
		items
			.filter((i) => page.url.pathname === i.href || page.url.pathname.startsWith(i.href + '/'))
			.sort((a, b) => b.href.length - a.href.length)[0]?.href ?? items[0].href
	);
</script>

<div class="mx-auto flex max-w-6xl gap-8 px-4 py-6 sm:px-6">
	<aside class="sticky top-18 hidden h-fit w-56 shrink-0 lg:block">
		<SideNav groups={settingsGroups} label="Settings" />
	</aside>
	<div class="flex min-w-0 flex-1 flex-col gap-4">
		<div class="lg:hidden">
			<Select
				value={here}
				options={items.map((i) => ({ value: i.href, label: i.label }))}
				onchange={(event) => goto((event.currentTarget as HTMLSelectElement).value)}
			/>
		</div>
		{@render children()}
	</div>
</div>

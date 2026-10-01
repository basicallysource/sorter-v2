<!--
	Settings: the side nav is a column on the surface plane, the full height
	beside the pages, and each column scrolls on its own. A page of forms is at
	most 1152px wide; a page whose main thing is a camera takes the whole width,
	up to 1800px. On a narrow screen the nav becomes a select above the page.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import SideNav from '$lib/components/SideNav.svelte';
	import Select from '$lib/components/Select.svelte';
	import { cameraSections, settingsGroups } from './nav';

	let { children } = $props();

	const items = settingsGroups.flatMap((g) => g.items);
	const wide = $derived(cameraSections.includes(page.params.section ?? ''));
	const here = $derived(
		items
			.filter((i) => page.url.pathname === i.href || page.url.pathname.startsWith(i.href + '/'))
			.sort((a, b) => b.href.length - a.href.length)[0]?.href ?? items[0].href
	);
</script>

<div class="flex min-h-0 flex-1">
	<aside class="hidden w-60 shrink-0 overflow-y-auto bg-surface px-3 py-5 lg:block">
		<SideNav groups={settingsGroups} label="Settings" />
	</aside>
	<div class="min-w-0 flex-1 lg:overflow-y-auto">
		<div
			class="flex flex-col gap-(--gap-panels) px-4 py-6 sm:px-8 {wide
				? 'max-w-[1800px]'
				: 'max-w-6xl'}"
		>
			<div class="lg:hidden">
				<Select
					label="Settings page"
					value={here}
					options={items.map((i) => ({ value: i.href, label: i.label }))}
					onchange={(href) => goto(href)}
				/>
			</div>
			{@render children()}
		</div>
	</div>
</div>

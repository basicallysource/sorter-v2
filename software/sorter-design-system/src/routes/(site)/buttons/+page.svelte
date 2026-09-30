<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import House from '@lucide/svelte/icons/house';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Trash from '@lucide/svelte/icons/trash-2';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Download from '@lucide/svelte/icons/download';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Button from '$lib/components/Button.svelte';
	import Panel from '$lib/components/Panel.svelte';

	let saving = $state(false);
	function save() {
		saving = true;
		setTimeout(() => (saving = false), 1500);
	}
</script>

<svelte:head><title>Buttons · Sorter design system</title></svelte:head>

<PageHeader
	title="Buttons"
	lead="Four variants and two sizes, all drawn in tints: nothing is a solid block of color. The label says what happens; an icon may lead it."
	doc="components"
/>

<SiteSection
	title="Variants"
	lead="One primary per panel or dialog: the thing to do. Everything else is secondary or ghost."
>
	<Specimen
		code={`<Button variant="primary" icon={House}>Home</Button>
<Button icon={RefreshCw}>Rescan</Button>
<Button variant="ghost">Cancel</Button>
<Button variant="danger" icon={Trash}>Delete profile</Button>`}
	>
		<div class="flex flex-wrap items-center gap-3">
			<Button variant="primary" icon={House}>Home</Button>
			<Button icon={RefreshCw}>Rescan</Button>
			<Button variant="ghost">Cancel</Button>
			<Button variant="danger" icon={Trash}>Delete profile</Button>
		</div>
	</Specimen>
	<div class="grid gap-4 text-sm md:grid-cols-2">
		<Panel flush>
			<ul class="divide-y divide-line">
				<li class="px-5 py-3">
					<span class="font-medium text-ink">Primary.</span>
					<span class="text-ink-muted">The one thing to do here, in the operator's color.</span>
				</li>
				<li class="px-5 py-3">
					<span class="font-medium text-ink">Secondary.</span>
					<span class="text-ink-muted">Any other action.</span>
				</li>
			</ul>
		</Panel>
		<Panel flush>
			<ul class="divide-y divide-line">
				<li class="px-5 py-3">
					<span class="font-medium text-ink">Ghost.</span>
					<span class="text-ink-muted"
						>The way out, and actions in a row of many (a camera's -1°, +1°).</span
					>
				</li>
				<li class="px-5 py-3">
					<span class="font-medium text-ink">Danger.</span>
					<span class="text-ink-muted"
						>Deletes or stops something for good, and asks first. Only in a confirmation.</span
					>
				</li>
			</ul>
		</Panel>
	</div>
</SiteSection>

<SiteSection
	title="Sizes"
	lead="md for a page or a dialog, sm inside a dense row or a panel's header. Both come from the size scale (Layout)."
>
	<Specimen code={`<Button size="sm" icon={Plus}>Add bin</Button>`}>
		<div class="flex flex-wrap items-center gap-3">
			<Button variant="primary">Save</Button>
			<Button>Rescan</Button>
			<Button variant="primary" size="sm">Save</Button>
			<Button size="sm" icon={Plus}>Add bin</Button>
			<Button size="sm" variant="ghost">Reset</Button>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Icon buttons"
	lead="An icon alone needs a name, which becomes its accessible name and its tooltip. Point at one."
>
	<Specimen code={`<Button variant="ghost" icon={Pencil} label="Rename profile" />`}>
		<div class="flex flex-wrap items-center gap-2">
			<Button variant="ghost" icon={Pencil} label="Rename profile" />
			<Button variant="ghost" icon={Download} label="Download samples" />
			<Button icon={Trash} label="Delete profile" />
			<Button size="sm" variant="ghost" icon={RefreshCw} label="Refresh" />
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="States"
	lead="Loading keeps the label and swaps the icon for the Spinner; the button stays full strength, because it is busy, not unavailable. Disabled fades it."
>
	<Specimen code={`<Button variant="primary" loading={saving} onclick={save}>Save</Button>`}>
		<div class="flex flex-wrap items-center gap-3">
			<Button variant="primary" loading={saving} onclick={save}>Save</Button>
			<Button loading>Connecting</Button>
			<Button disabled>Save name</Button>
			<Button variant="primary" disabled>Home</Button>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="As a link"
	lead="Given an address it is a link that looks like a button, for going somewhere rather than doing something."
>
	<Specimen code={`<Button href="/example/settings" icon={ArrowRight}>Open settings</Button>`}>
		<Button href="/example/settings" icon={ArrowRight}>Open settings</Button>
	</Specimen>
</SiteSection>

<SiteSection
	title="In a row"
	lead="Buttons keep a gap of at least 8px, so two never touch. The way out comes first and the primary last, at the right of a panel's footer or a dialog's."
>
	<Panel title="Profile" flush>
		<p class="px-5 pb-4 text-sm text-ink-muted">Sorting profile September, 214 categories.</p>
		{#snippet footer()}
			<Button variant="ghost">Cancel</Button>
			<Button>Duplicate</Button>
			<Button variant="primary">Save</Button>
		{/snippet}
	</Panel>
</SiteSection>

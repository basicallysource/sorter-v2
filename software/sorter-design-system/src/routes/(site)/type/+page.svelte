<script lang="ts">
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import DoDont from '$lib/site/DoDont.svelte';
	import Button from '$lib/components/Button.svelte';

	const scale = [
		{
			role: 'Display',
			spec: '24px · semibold · tight',
			classes: 'text-2xl font-semibold tracking-tight',
			sample: 'Sorter design system',
			use: 'The title of a page that introduces an area: these pages, a Hive landing page, a setup step.'
		},
		{
			role: 'Title',
			spec: '20px · semibold · tight',
			classes: 'text-xl font-semibold tracking-tight',
			sample: 'General',
			use: "An app page's title."
		},
		{
			role: 'Heading',
			spec: '16px · semibold',
			classes: 'text-base font-semibold',
			sample: 'Sample capture',
			use: "A panel's title, a dialog's title."
		},
		{
			role: 'Body',
			spec: '14px · regular',
			classes: 'text-sm',
			sample: 'Save a photo of each part as it is classified.',
			use: 'Everything someone reads: settings, help, table cells, messages. The smallest readable size.'
		},
		{
			role: 'Emphasis',
			spec: '14px · medium',
			classes: 'text-sm font-medium',
			sample: 'Burst rate',
			use: "A setting's name, a row's name, a button's label."
		},
		{
			role: 'Label',
			spec: '14px · medium · muted · sentence case',
			classes: 'label',
			sample: 'Hardware',
			use: "A group's name in a nav, a stat's name, a table's head. Never in capitals."
		},
		{
			role: 'Meta',
			spec: '12px · medium',
			classes: 'text-xs font-medium',
			sample: 'Distributed',
			use: 'A badge, a count, a bin code, a time: short and skippable.'
		},
		{
			role: 'Number',
			spec: '24px · medium · tabular figures',
			classes: 'num text-2xl font-medium',
			sample: '14.7',
			use: "A stat. The num class uses Geist's tabular figures, so numbers line up and do not jitter as they change."
		}
	];
</script>

<svelte:head><title>Type · Sorter design system</title></svelte:head>

<PageHeader
	title="Type"
	lead="Geist for words and Geist Mono for what someone copies. Five sizes, and 14px is the smallest anyone has to read."
	doc="type"
/>

<SiteSection title="The scale">
	<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
		{#each scale as row (row.role)}
			<li class="grid gap-x-8 gap-y-2 px-5 py-4 md:grid-cols-[10rem_minmax(0,1fr)_minmax(0,18rem)]">
				<div>
					<div class="text-sm font-medium text-ink">{row.role}</div>
					<div class="text-xs text-ink-muted">{row.spec}</div>
				</div>
				<div class="{row.classes} min-w-0 truncate text-ink">{row.sample}</div>
				<p class="text-sm text-ink-muted">{row.use}</p>
			</li>
		{/each}
	</ul>
</SiteSection>

<SiteSection
	title="Mono"
	lead="Geist Mono, for what someone might copy or compare character by character: addresses, hashes, ids, part numbers, hex values. Numbers that change use Geist's tabular figures instead."
>
	<Specimen>
		<div class="flex flex-col gap-2 text-sm">
			<div>
				<span class="text-ink-muted">Address</span>
				<span class="font-mono text-ink">ws://sorter.local:8000/ws</span>
			</div>
			<div>
				<span class="text-ink-muted">Part</span> <span class="font-mono text-ink">3794b</span>
			</div>
			<div>
				<span class="text-ink-muted">Bin</span> <span class="num text-ink">L2 · S0 · B1</span>
			</div>
		</div>
	</Specimen>
</SiteSection>

<SiteSection title="How the words are written">
	<DoDont
		on="surface"
		wrongNote="Title Case, a label in capitals that is really a sentence, and a button that says what a button is."
		rightNote="Sentence case everywhere. The button says what happens. The help says what the setting does, in plain words."
	>
		{#snippet wrong()}
			<div>
				<div class="text-base font-semibold text-ink">Sample Capture Settings</div>
				<div class="mt-2 text-xs font-semibold tracking-wider text-ink-muted uppercase">
					Enable this to save images of parts for model training
				</div>
				<div
					class="mt-3 inline-flex h-9 items-center border border-line-strong px-3.5 text-sm font-medium text-ink"
				>
					Submit
				</div>
			</div>
		{/snippet}
		{#snippet right()}
			<div>
				<div class="text-base font-semibold text-ink">Sample capture</div>
				<div class="mt-2 text-sm text-ink-muted">
					Save a photo of each part as it is classified.
				</div>
				<div class="mt-3"><Button variant="primary">Save</Button></div>
			</div>
		{/snippet}
	</DoDont>
</SiteSection>

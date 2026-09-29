<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import Switch from '$lib/components/Switch.svelte';
	import Input from '$lib/components/Input.svelte';
	import Button from '$lib/components/Button.svelte';
	import { rules } from '$lib/site/rules';

	let capture = $state(true);
	let burst = $state(6);
</script>

<svelte:head><title>Sorter design system</title></svelte:head>

<PageHeader
	title="Sorter design system"
	lead="How the Sorter's own screens and Hive look, and how they are built. Every component on these pages is the one to copy into those apps; the rules say why it looks the way it does."
/>

<SiteSection
	title="Four planes"
	lead="Everything on a screen sits on one of four planes, and a plane is told apart by its fill, never by an outline. That one idea replaces most of the borders an app would otherwise draw."
>
	<div class="relative">
		<div class="label mb-3">1 · Canvas: the page, which this text sits on</div>
		<div class="rounded-panel bg-surface p-5 sm:max-w-xl">
			<div class="label mb-3">2 · Surface: a panel</div>
			<p class="text-sm text-ink-muted">One job's worth of content. No border, no shadow.</p>
			<div class="mt-4 rounded-control bg-well p-4">
				<div class="label">3 · Well: sunk into the panel</div>
				<p class="mt-1 text-sm text-ink-muted">A chart, a preview, an empty list.</p>
			</div>
		</div>
		<div
			class="mt-4 rounded-panel border border-line bg-raised p-4 sm:absolute sm:top-16 sm:right-0 sm:mt-0 sm:w-64 lg:right-8"
		>
			<div class="label">4 · Raised: it floats</div>
			<p class="mt-1 text-sm text-ink-muted">
				Popovers, menus, dialogs. The only plane with a line around it. Nothing has a shadow.
			</p>
		</div>
	</div>
</SiteSection>

<SiteSection
	title="What it looks like"
	lead="A few settings from the machine, built from the components here. The rows are divided by one line each; the panel needs no outline because the canvas around it is a different color."
>
	<div>
		<Panel
			title="Sample capture"
			description="Photos of parts the machine saves for training."
			flush
		>
			<div class="divide-y divide-line">
				<SettingRow label="Capture samples" help="Save a photo of each part as it is classified.">
					<Switch bind:checked={capture} label="Capture samples" />
				</SettingRow>
				<SettingRow
					label="Burst rate"
					help="The most photos to save in a minute."
					for="overview-burst"
				>
					<Input id="overview-burst" type="number" bind:value={burst} unit="/min" class="w-28" />
				</SettingRow>
			</div>
			{#snippet footer()}
				<Button variant="ghost">Reset</Button>
				<Button variant="primary">Save</Button>
			{/snippet}
		</Panel>
	</div>
</SiteSection>

<SiteSection
	title="The rules"
	lead="The few things that make it hold together. Each has a page of examples."
>
	<ol class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
		{#each rules as rule, i (rule.id)}
			<li>
				<a
					href="/rules#{rule.id}"
					class="group flex items-start gap-4 px-5 py-3.5 transition-colors hover:bg-hover"
				>
					<span class="num w-5 shrink-0 pt-px text-sm text-ink-faint">{i + 1}</span>
					<span class="min-w-0 flex-1">
						<span class="block text-sm font-medium text-ink">{rule.title}</span>
						<span class="block text-sm text-ink-muted">{rule.summary}</span>
					</span>
					<ArrowRight
						size={16}
						class="mt-0.5 shrink-0 text-ink-faint transition-colors group-hover:text-ink"
					/>
				</a>
			</li>
		{/each}
	</ol>
</SiteSection>

<SiteSection title="Using it">
	<div class="grid gap-4 md:grid-cols-3">
		<Panel title="Copy, don't redraw">
			<p class="text-sm text-ink-muted">
				A component lives in <code class="font-mono text-ink">src/lib/components/</code>. An app
				copies the file as it is. A change is made here first, then copied again.
			</p>
		</Panel>
		<Panel title="Tokens, not colors">
			<p class="text-sm text-ink-muted">
				<code class="font-mono text-ink">src/app.css</code> holds every color, both modes. Markup
				names a token (<code class="font-mono text-ink">bg-surface</code>), never a hex value.
			</p>
		</Panel>
		<Panel title="Read the rules">
			<p class="text-sm text-ink-muted">
				<code class="font-mono text-ink">docs/</code> says what each piece is for. Start with
				<a href="/rules" class="text-primary-ink hover:underline">the rules</a>.
			</p>
		</Panel>
	</div>
</SiteSection>

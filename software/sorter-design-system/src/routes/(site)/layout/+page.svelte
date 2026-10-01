<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Plus from '@lucide/svelte/icons/plus';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Button from '$lib/components/Button.svelte';
	import AppPageHeader from '$lib/components/PageHeader.svelte';

	const spacing = [
		{
			px: 4,
			use: 'Between an icon and its word in a small control; between a label and its sentence.'
		},
		{ px: 8, use: 'Between controls in a row; the least gap between two outlined things.' },
		{ px: 16, use: 'Between panels, and between a page title and the first panel.' },
		{ px: 20, use: "A panel's side padding, so its title, rows and footer line up." },
		{ px: 24, use: 'Around the page content on a wide screen (16 on a phone).' },
		{ px: 32, use: 'Between the side nav and the content.' }
	];
</script>

<svelte:head><title>Layout · Sorter design system</title></svelte:head>

<PageHeader
	title="Layout"
	lead="The app shell, the two page layouts every screen is one of, and the spacing that keeps them in line. Layout does the grouping, so nothing needs a box around it to belong together."
	doc="layout"
/>

{#snippet bar()}
	<div class="flex h-4 items-center gap-1.5 border-b border-line bg-surface px-2">
		<span class="size-1.5 bg-primary"></span>
		<span class="h-1 w-5 bg-pressed"></span>
		<span class="h-1 w-4 bg-pressed"></span>
		<span class="h-1 w-4 bg-pressed"></span>
	</div>
{/snippet}

<SiteSection
	title="The shell"
	lead="A top bar on the surface plane with the one line under it, and the screen under it exactly the rest of the window: an app screen never scrolls as a page. What can grow (a list, a settings column) scrolls inside its own panel or column. On a phone it is one column that scrolls."
>
	<div class="grid gap-6 md:grid-cols-2">
		<figure class="flex flex-col gap-3">
			<div
				class="flex aspect-[16/10] flex-col overflow-hidden rounded-panel border border-line bg-canvas"
			>
				{@render bar()}
				<div class="flex min-h-0 flex-1">
					<div class="flex w-1/5 flex-col gap-1 bg-surface p-2">
						<span class="h-1.5 w-full rounded-item bg-primary-soft"></span>
						<span class="h-1.5 w-4/5 bg-pressed"></span>
						<span class="h-1.5 w-3/5 bg-pressed"></span>
						<span class="mt-2 h-1.5 w-4/5 bg-pressed"></span>
						<span class="h-1.5 w-3/5 bg-pressed"></span>
					</div>
					<div class="flex flex-1 flex-col gap-2 p-3">
						<span class="h-2 w-1/4 bg-ink-faint"></span>
						<div class="h-1/4 rounded-panel bg-surface"></div>
						<div class="h-2/5 rounded-panel bg-surface"></div>
					</div>
				</div>
			</div>
			<figcaption class="text-sm">
				<span class="font-medium text-ink">Settings.</span>
				<span class="text-ink-muted"
					>The side nav is a column on the surface plane, and the page's panels sit on the canvas
					beside it, each scrolling on its own. Below 1024px the side nav becomes a select above the
					page.</span
				>
			</figcaption>
		</figure>
		<figure class="flex flex-col gap-3">
			<div
				class="flex aspect-[16/10] flex-col overflow-hidden rounded-panel border border-line bg-canvas"
			>
				{@render bar()}
				<div
					class="grid min-h-0 flex-1 grid-cols-[1fr_1fr_0.9fr] grid-rows-[auto_1fr_1fr] gap-2 p-2"
				>
					<div class="col-span-2 row-span-2 grid grid-cols-2 gap-2">
						<div class="flex flex-col overflow-hidden rounded-panel bg-surface">
							<span class="h-2 shrink-0"></span><span class="flex-1 bg-media"></span>
						</div>
						<div class="flex flex-col overflow-hidden rounded-panel bg-surface">
							<span class="h-2 shrink-0"></span><span class="flex-1 bg-media"></span>
						</div>
					</div>
					<div class="h-8 rounded-panel bg-surface"></div>
					<div class="row-span-2 rounded-panel bg-surface"></div>
					<div class="col-span-2 flex flex-col overflow-hidden rounded-panel bg-surface">
						<span class="h-2 shrink-0"></span><span class="flex-1 bg-media"></span>
					</div>
				</div>
			</div>
			<figcaption class="text-sm">
				<span class="font-medium text-ink">Dashboard.</span>
				<span class="text-ink-muted"
					>Exactly the window: the cameras fill the left, the status and numbers sit top right, and
					the recent pieces take the rest and scroll in their panel. On a phone the status and its
					Home come first, then the cameras, then the rest.</span
				>
			</figcaption>
		</figure>
	</div>
	<div>
		<Button href="/example" variant="ghost" icon={ArrowRight}>See both in the example app</Button>
	</div>
</SiteSection>

<SiteSection
	title="A page"
	lead="A title and one sentence on the canvas, with the page's own actions at the right, then panels, one per job, 16px apart. On a phone the actions wrap under the sentence. A panel's title says what it is for; the page never needs a second heading level above its panels."
>
	<Specimen
		on="canvas"
		code={`<div class="flex flex-col gap-(--gap-panels)">
	<PageHeader title="Sorting profiles" description="...">
		{#snippet actions()}<Button icon={Plus}>New profile</Button>{/snippet}
	</PageHeader>
	<Panel ...>...</Panel>
</div>`}
	>
		<div class="flex flex-col gap-(--gap-panels)">
			<AppPageHeader
				title="Sorting profiles"
				description="Which bin each part goes to. The machine sorts by one profile at a time."
			>
				{#snippet actions()}<Button icon={Plus}>New profile</Button>{/snippet}
			</AppPageHeader>
			<div class="rounded-panel bg-surface px-5 py-4">
				<div class="text-base font-semibold text-ink">September</div>
				<div class="mt-0.5 text-sm text-ink-muted">In use. 36 bins, by part.</div>
			</div>
			<div class="rounded-panel bg-surface px-5 py-4">
				<div class="text-base font-semibold text-ink">Bulk by color</div>
			</div>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Spacing"
	lead="A 4px grid, and a short list of steps. The same step is used for the same job everywhere."
>
	<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
		{#each spacing as step (step.px)}
			<li class="flex items-center gap-5 px-5 py-3">
				<span class="num w-10 shrink-0 text-sm text-ink">{step.px}</span>
				<span class="h-3 shrink-0 bg-primary" style:width="{step.px}px"></span>
				<span class="text-sm text-ink-muted">{step.use}</span>
			</li>
		{/each}
	</ul>
</SiteSection>

<SiteSection
	title="Sizes"
	lead="One scale, so everything steps together: controls, badges, switches, rows, the top bar and the current page's mark all come from the same tokens. Controls are 36px, 30px in a dense row."
>
	<div class="flex flex-wrap items-center gap-3 rounded-panel bg-surface p-6">
		<div
			class="flex h-(--size-control) items-center rounded-control bg-well px-(--pad-control) text-sm text-ink"
		>
			Control, 36px
		</div>
		<div
			class="flex h-(--size-control-sm) items-center rounded-control bg-well px-(--pad-control-sm) text-sm text-ink"
		>
			Dense, 30px
		</div>
		<div
			class="flex h-(--size-badge) items-center rounded-badge bg-well px-(--pad-badge) text-xs text-ink"
		>
			Badge, 22px
		</div>
	</div>
</SiteSection>

<SiteSection
	title="Narrow screens"
	lead="Everything works at 390px wide: the top bar folds its pages into one menu named for the current page, the side nav turns into a select, rows stack their control under their name, a page's actions wrap under its title, and no page scrolls sideways."
>
	<div class="bg-surface p-5 text-sm text-ink-muted">
		The page's own order is the phone's order, so what someone needs first comes first in the
		markup.
	</div>
</SiteSection>

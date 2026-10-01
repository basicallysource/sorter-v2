<script lang="ts">
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Button from '$lib/components/Button.svelte';

	let refreshing = $state(false);
	let copied = $state(38);

	function refresh() {
		refreshing = true;
		setTimeout(() => (refreshing = false), 1500);
	}

	$effect(() => {
		const timer = setInterval(() => (copied = copied >= 100 ? 0 : copied + 2), 250);
		return () => clearInterval(timer);
	});
</script>

<svelte:head><title>Loading · Sorter design system</title></svelte:head>

<PageHeader
	title="Loading"
	lead="The Spinner is the one moving thing that says wait. It takes the color of the text beside it, and it keeps moving even when motion is reduced, because a still one looks hung."
	doc="loading"
/>

<SiteSection
	title="The Spinner"
	lead="Four squares, one lit at a time. Sizes 12, 16, 24 and 32. It draws only itself: a caller places and pads it."
>
	<Specimen code={`<Spinner size={16} />`}>
		<div class="flex flex-wrap items-center gap-8 text-ink">
			<Spinner size={12} />
			<Spinner size={16} />
			<Spinner size={24} />
			<Spinner size={32} />
			<span class="text-primary-ink"><Spinner size={24} /></span>
			<span class="text-ink-muted"><Spinner size={24} /></span>
		</div>
	</Specimen>
</SiteSection>

<SiteSection
	title="Where it goes"
	lead="Beside a sentence that says what is loading; in the button that started it; in the middle of a panel whose content is on its way."
>
	<div class="grid gap-4 md:grid-cols-2">
		<Specimen>
			<div class="flex flex-col items-start gap-4">
				<div class="flex items-center gap-2 text-sm text-ink-muted">
					<Spinner size={16} />Checking the Hive connection
				</div>
				<Button icon={RefreshCw} loading={refreshing} onclick={refresh}>Rescan cameras</Button>
			</div>
		</Specimen>
		<Panel title="Local models">
			<div class="flex flex-col items-center gap-3 py-8 text-sm text-ink-muted">
				<Spinner size={24} />Loading the models on this machine
			</div>
		</Panel>
	</div>
</SiteSection>

<SiteSection
	title="Skeletons"
	lead="When the shape of what is coming is known (the rows of a list, a picture), a skeleton holds its place so nothing jumps when it lands. It fades; it never spins."
>
	<Panel title="Recent pieces" flush>
		<ul class="divide-y divide-line" aria-busy="true">
			{#each [0, 1, 2] as row (row)}
				<li class="flex gap-3 px-4 py-3">
					<Skeleton class="size-14 shrink-0" />
					<div class="flex flex-1 flex-col gap-2 pt-1">
						<Skeleton class="h-3.5 w-3/5" />
						<Skeleton class="h-3.5 w-1/4" />
						<Skeleton class="h-3.5 w-2/5" />
					</div>
				</li>
			{/each}
		</ul>
	</Panel>
</SiteSection>

<SiteSection
	title="Progress"
	lead="When how far along is known, a bar says so, with the numbers beside it. When it is not, it is the Spinner."
>
	<Specimen>
		<div class="flex max-w-md flex-col gap-2">
			<div class="flex items-baseline justify-between text-sm">
				<span class="text-ink">Copying samples</span>
				<span class="num text-ink-muted">{copied}%</span>
			</div>
			<ProgressBar value={copied} label="Copying samples" />
		</div>
	</Specimen>
</SiteSection>

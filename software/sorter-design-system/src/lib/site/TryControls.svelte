<!--
	The choices still open, switched live on every page, and remembered in
	this browser. /choices shows each one side by side.
-->
<script lang="ts">
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Popover from '$lib/components/Popover.svelte';
	import Button from '$lib/components/Button.svelte';
	import Select from '$lib/components/Select.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { afterNavigate } from '$app/navigation';
	import { choices, dimensions } from '$lib/site/choices.svelte';

	let open = $state(false);
	afterNavigate(() => (open = false));
</script>

<Popover label="Try the open choices" placement="bottom-end" width="22rem" bind:open>
	{#snippet trigger(props)}
		<Button {...props} size="sm" variant="ghost" icon={SlidersHorizontal}>
			<span class="max-sm:sr-only">Try</span>
		</Button>
	{/snippet}
	<div class="flex flex-col gap-4">
		<p class="text-ink-muted">
			Choices still open. Each changes every page at once, and stays until changed.
		</p>
		{#each dimensions as dimension (dimension.key)}
			<div class="flex flex-col gap-1.5">
				<span class="font-medium text-ink">{dimension.name}</span>
				{#if dimension.options.length > 5}
					<Select
						label={dimension.name}
						size="sm"
						value={choices.current[dimension.key]}
						options={dimension.options.map((o) => ({
							value: o.value,
							label: `${o.letter} · ${o.name}${o.today ? ' (today)' : ''}`
						}))}
						onchange={(v) => choices.set(dimension.key, v)}
					/>
				{:else}
					<SegmentedControl
						label={dimension.name}
						size="sm"
						full
						value={choices.current[dimension.key]}
						options={dimension.options.map((o) => ({
							value: o.value,
							label:
								dimension.key === 'corners' || dimension.key === 'density'
									? o.name.split(' ')[0]
									: o.letter
						}))}
						onchange={(v) => choices.set(dimension.key, v)}
					/>
				{/if}
			</div>
		{/each}
		<div class="flex items-center justify-between gap-2">
			<Button size="sm" variant="ghost" onclick={() => choices.reset()}>Back to today</Button>
			<Button size="sm" href="/choices" icon={ArrowRight}>Compare them</Button>
		</div>
	</div>
</Popover>

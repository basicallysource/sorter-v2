<script module lang="ts">
	export type ProviderInfo = {
		id: string;
		label: string;
		description: string;
	};
</script>

<script lang="ts">
	import { SelectMenu } from '$lib/components/primitives';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Cloud from '@lucide/svelte/icons/cloud';
	import Globe from '@lucide/svelte/icons/globe';
	import Sparkles from '@lucide/svelte/icons/sparkles';

	let {
		options,
		selected = $bindable(''),
		active = ''
	}: {
		options: ProviderInfo[];
		selected?: string;
		active?: string;
	} = $props();

	// Per-provider glyph so a third-party API reads differently from a hosted
	// model at a glance; anything unrecognized falls back to a generic cloud.
	const PROVIDER_ICONS: Record<string, typeof Cloud> = {
		brickognize: Globe,
		hive_basically: Sparkles
	};

	function iconFor(id: string) {
		return PROVIDER_ICONS[id] ?? Cloud;
	}

	let open = $state(false);
	let current = $derived(options.find((p) => p.id === selected));
	let TriggerIcon = $derived(iconFor(selected));

	function choose(id: string) {
		selected = id;
		open = false;
	}
</script>

<SelectMenu bind:open searchable={false} width={380}>
	{#snippet trigger()}
		<span
			class="inline-flex min-w-[18rem] items-center justify-between gap-3 border border-line bg-white px-3 py-2 text-sm text-ink transition-colors hover:bg-surface"
		>
			<span class="inline-flex items-center gap-2">
				<TriggerIcon size={16} class="text-ink-muted" />
				{current?.label ?? 'Select…'}
			</span>
			<ChevronDown size={16} class="text-ink-muted" />
		</span>
	{/snippet}
	{#each options as p (p.id)}
		{@const Icon = iconFor(p.id)}
		<button
			type="button"
			onclick={() => choose(p.id)}
			class="flex w-full items-start gap-3 border-b border-line bg-white px-3 py-3 text-left transition-colors last:border-b-0 hover:bg-surface"
		>
			<Icon size={16} class="mt-0.5 shrink-0 text-ink-muted" />
			<span class="min-w-0 flex-1">
				<span class="flex items-center gap-2 text-sm text-ink">
					{p.label}
					{#if p.id === active}
						<span class="border border-line bg-surface px-1.5 py-0.5 text-xs text-ink-muted">
							current
						</span>
					{/if}
				</span>
				<span class="mt-1 block text-sm text-ink-muted">{p.description}</span>
			</span>
			{#if p.id === selected}
				<Check size={16} class="mt-0.5 shrink-0 text-primary-ink" />
			{/if}
		</button>
	{/each}
</SelectMenu>

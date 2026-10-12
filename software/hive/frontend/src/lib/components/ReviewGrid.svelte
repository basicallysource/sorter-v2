<!--
	The list on a review page (Piece samples, Channel samples): the cards of a
	ReviewQueue in a grid or as rows, loading the next page as the end scrolls
	into view (the button is the fallback), and saying when the list ends. What
	a card shows is the page's own (the `item` snippet).
-->
<script lang="ts" generics="T">
	import type { Component, Snippet } from 'svelte';
	import type { ReviewQueue } from '$lib/reviewQueue.svelte';
	import Alert from './Alert.svelte';
	import Button from './Button.svelte';
	import EmptyState from './EmptyState.svelte';
	import Panel from './Panel.svelte';
	import Spinner from './Spinner.svelte';

	let {
		queue,
		item,
		layout = 'grid',
		gridClass = 'grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-3',
		emptyIcon,
		emptyTitle,
		empty,
		emptyAction
	}: {
		queue: ReviewQueue<T>;
		item: Snippet<[T]>;
		layout?: 'grid' | 'rows';
		gridClass?: string;
		emptyIcon?: Component<{ size?: number; class?: string }>;
		emptyTitle: string;
		empty?: Snippet;
		emptyAction?: Snippet;
	} = $props();

	let sentinel = $state<HTMLElement | null>(null);

	// Pull the next page as the end of the list nears the viewport.
	$effect(() => {
		const el = sentinel;
		const q = queue;
		if (!el) return;
		const obs = new IntersectionObserver(
			(entries) => {
				if (entries.some((e) => e.isIntersecting)) void q.loadMore();
			},
			{ rootMargin: '600px' }
		);
		obs.observe(el);
		return () => obs.disconnect();
	});
</script>

{#if queue.error}<Alert tone="danger">{queue.error}</Alert>{/if}

{#if queue.loading}
	<div class="flex justify-center py-16"><Spinner size={32} /></div>
{:else if queue.items.length === 0}
	{#if !queue.error}
		<Panel><EmptyState icon={emptyIcon} title={emptyTitle} action={emptyAction} children={empty} /></Panel>
	{/if}
{:else}
	{#if layout === 'grid'}
		<div class={gridClass}>
			{#each queue.items as it (queue.key(it))}
				{@render item(it)}
			{/each}
		</div>
	{:else}
		<div class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
			{#each queue.items as it (queue.key(it))}
				{@render item(it)}
			{/each}
		</div>
	{/if}

	<div class="flex justify-center">
		{#if queue.hasMore}
			<div bind:this={sentinel} class="flex justify-center py-2">
				<Button size="sm" loading={queue.loadingMore} onclick={() => void queue.loadMore()}>Load more</Button>
			</div>
		{:else}
			<span class="num text-sm text-ink-muted">The end of the list, {queue.items.length.toLocaleString()} shown</span>
		{/if}
	</div>
{/if}

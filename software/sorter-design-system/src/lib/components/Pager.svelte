<!--
	docs/components.md#pager. Where you are in a long list and the way
	through it: which of how many are shown, the first, previous, next and
	last page, and the page's number to type. It holds no data: the list is
	the app's, and `onpage` asks for another page (1-based). Put one above a
	list and one under it, so the end of a long page is not a scroll back to
	the top. `loading` holds the buttons while a page is on its way. A list
	that can only walk (it cannot read a page it has not been to) sets
	`jump={false}`: previous and next, and the page number as words.

	<Pager label="Pieces" page={3} pages={734} from={101} to={150} total={36652}
		noun="pieces" onpage={go} />
-->
<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronsLeft from '@lucide/svelte/icons/chevrons-left';
	import ChevronsRight from '@lucide/svelte/icons/chevrons-right';
	import Button from './Button.svelte';
	import Input from './Input.svelte';

	let {
		page,
		pages,
		from,
		to,
		total,
		noun = 'results',
		label,
		loading = false,
		jump = true,
		onpage
	}: {
		// The page shown, counted from 1, and how many there are.
		page: number;
		pages: number;
		// The first and last item shown, counted from 1, and how many there are.
		from: number;
		to: number;
		total: number;
		// What the items are called, in the plural ("pieces").
		noun?: string;
		// The accessible name of the pager ("Pieces").
		label: string;
		loading?: boolean;
		// False for a list that cannot go to a page it has not been to.
		jump?: boolean;
		onpage: (page: number) => void;
	} = $props();

	let typed = $state<string | number | null>(null);
	$effect(() => {
		typed = page;
	});

	function go(next: number) {
		const clamped = Math.min(Math.max(Math.round(next), 1), Math.max(pages, 1));
		if (clamped !== page) onpage(clamped);
		else typed = page;
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'Enter') return;
		event.preventDefault();
		const n = Number(typed);
		if (Number.isFinite(n) && typed !== '' && typed !== null) go(n);
		else typed = page;
	}
</script>

<nav
	aria-label="{label} pages"
	class="flex flex-wrap items-center justify-end gap-x-4 gap-y-1 text-sm"
>
	<span class="num text-ink-muted">
		{#if total > 0}
			{from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
			{noun}
		{:else}
			No {noun}
		{/if}
	</span>
	<div class="flex items-center gap-1">
		{#if jump}
			<Button
				size="sm"
				variant="ghost"
				icon={ChevronsLeft}
				label="First page"
				disabled={page <= 1 || loading}
				onclick={() => go(1)}
			/>
		{/if}
		<Button
			size="sm"
			variant="ghost"
			icon={ChevronLeft}
			label="Previous page"
			disabled={page <= 1 || loading}
			onclick={() => go(page - 1)}
		/>
		{#if jump}
			<label class="flex items-center gap-2 px-1 text-ink-muted">
				Page
				<Input
					size="sm"
					inputmode="numeric"
					bind:value={typed}
					{onkeydown}
					disabled={pages <= 1}
					aria-label="Page number"
					class="w-16"
				/>
				of <span class="num">{pages.toLocaleString()}</span>
			</label>
		{:else}
			<span class="num px-1 text-ink-muted"
				>Page {page.toLocaleString()} of {pages.toLocaleString()}</span
			>
		{/if}
		<Button
			size="sm"
			variant="ghost"
			icon={ChevronRight}
			label="Next page"
			disabled={page >= pages || loading}
			onclick={() => go(page + 1)}
		/>
		{#if jump}
			<Button
				size="sm"
				variant="ghost"
				icon={ChevronsRight}
				label="Last page"
				disabled={page >= pages || loading}
				onclick={() => go(pages)}
			/>
		{/if}
	</div>
</nav>

<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Button from '$lib/components/ui/Button.svelte';
	import Select from '$lib/components/ui/Select.svelte';

	type Props = {
		pageSize: number;
		pageSizeOptions: readonly number[];
		currentPage: number;
		totalPages: number;
		summary: string;
		visiblePageNumbers: number[];
		onPageSizeChange: (size: number) => void;
		onPageChange: (page: number) => void;
	};

	const props: Props = $props();
</script>

<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 text-sm text-ink-muted">
	<div class="flex items-center gap-2">
		<span>Per page</span>
		<Select
			label="Profiles per page"
			size="sm"
			class="w-20"
			value={String(props.pageSize)}
			options={props.pageSizeOptions.map((option) => ({ value: String(option), label: String(option) }))}
			onchange={(value) => props.onPageSizeChange(Number(value))}
		/>
	</div>
	<p>{props.summary}</p>
	<nav aria-label="Pages" class="flex items-center gap-1">
		<Button
			size="sm"
			variant="ghost"
			icon={ChevronLeft}
			disabled={props.currentPage <= 1}
			onclick={() => props.onPageChange(props.currentPage - 1)}
		>
			Previous
		</Button>
		{#each props.visiblePageNumbers as pageNumber}
			<Button
				size="sm"
				variant={pageNumber === props.currentPage ? 'primary' : 'ghost'}
				aria-current={pageNumber === props.currentPage ? 'page' : undefined}
				onclick={() => props.onPageChange(pageNumber)}
			>
				{pageNumber}
			</Button>
		{/each}
		<Button
			size="sm"
			variant="ghost"
			disabled={props.currentPage >= props.totalPages}
			onclick={() => props.onPageChange(props.currentPage + 1)}
		>
			Next
			<ChevronRight size={14} />
		</Button>
	</nav>
</div>

<script lang="ts">
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

<div
	class="mt-4 grid items-center gap-3 border border-border bg-surface px-4 py-3 text-sm text-text-muted md:grid-cols-[auto_1fr_auto]"
>
	<label class="flex items-center gap-2 text-sm text-text-muted">
		<span>Per page</span>
		<select
			value={String(props.pageSize)}
			onchange={(event) =>
				props.onPageSizeChange(Number((event.currentTarget as HTMLSelectElement).value))}
			class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
		>
			{#each props.pageSizeOptions as option}
				<option value={option}>{option}</option>
			{/each}
		</select>
	</label>
	<div class="text-center">{props.summary}</div>
	<div class="flex items-center justify-end gap-1">
		<button
			type="button"
			onclick={() => props.onPageChange(props.currentPage - 1)}
			disabled={props.currentPage <= 1}
			class="border border-border px-3 py-1.5 text-text transition-colors hover:bg-bg disabled:opacity-50"
			>Previous</button
		>
		{#each props.visiblePageNumbers as pageNumber}
			<button
				type="button"
				onclick={() => props.onPageChange(pageNumber)}
				class="border px-3 py-1.5 transition-colors {pageNumber === props.currentPage
					? 'border-primary bg-primary text-primary-contrast'
					: 'border-border text-text hover:bg-bg'}"
			>
				{pageNumber}
			</button>
		{/each}
		<button
			type="button"
			onclick={() => props.onPageChange(props.currentPage + 1)}
			disabled={props.currentPage >= props.totalPages}
			class="border border-border px-3 py-1.5 text-text transition-colors hover:bg-bg disabled:opacity-50"
			>Next</button
		>
	</div>
</div>

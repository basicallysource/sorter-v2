<script lang="ts">
	import type { AnnotatorApi } from '$lib/components/annotator-api.svelte';

	interface Props {
		annotatorApi: AnnotatorApi;
	}

	let { annotatorApi }: Props = $props();
</script>

<div class="border border-border bg-white">
	<div class="flex items-center justify-between border-b border-border px-4 py-2.5">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Annotator</h2>
		<span class="text-[11px] font-medium {annotatorApi.isDirty ? 'text-[#A16207]' : annotatorApi.hasSavedBaseline ? 'text-success' : 'text-text-muted'}">
			{#if annotatorApi.isDirty}Unsaved{:else if annotatorApi.hasSavedBaseline}Saved{:else}Not saved{/if}
		</span>
	</div>
	<div class="space-y-3 p-3">
		<div class="grid grid-cols-4 gap-1.5">
			<button onclick={annotatorApi.undo} class="flex flex-col items-center gap-1 border border-border px-1 py-2 text-text-muted transition-colors hover:bg-bg" title="Undo">
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a4 4 0 014 4v0a4 4 0 01-4 4H3m0-8l4-4m-4 4l4 4" /></svg>
				<span class="text-[10px]">Undo</span>
			</button>
			<button onclick={annotatorApi.redo} class="flex flex-col items-center gap-1 border border-border px-1 py-2 text-text-muted transition-colors hover:bg-bg" title="Redo">
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 10H11a4 4 0 00-4 4v0a4 4 0 004 4h10m0-8l-4-4m4 4l-4 4" /></svg>
				<span class="text-[10px]">Redo</span>
			</button>
			<button
				onclick={annotatorApi.deleteSelected}
				disabled={annotatorApi.selectedCount === 0}
				class="flex flex-col items-center gap-1 border px-1 py-2 transition-colors disabled:cursor-not-allowed disabled:border-border disabled:text-border {annotatorApi.selectedCount === 0 ? '' : 'border-primary/20 text-primary hover:bg-primary-light'}"
				title="Delete selected"
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
				<span class="text-[10px]">Delete</span>
			</button>
			<button onclick={annotatorApi.clearAll} class="flex flex-col items-center gap-1 border border-warning/30 px-1 py-2 text-[#A16207] transition-colors hover:bg-warning/[0.1]" title="Clear all">
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
				<span class="text-[10px]">Clear</span>
			</button>
		</div>

		<div class="flex gap-1.5">
			<button onclick={annotatorApi.revert} class="flex flex-1 items-center justify-center gap-1.5 border border-border px-2 py-1.5 text-[11px] text-text-muted transition-colors hover:bg-bg" title="Discard changes and restore last saved state">
				<svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
				Cancel
			</button>
			{#if annotatorApi.hasSeedBoxes}
				<button onclick={annotatorApi.loadSorterBoxes} class="flex flex-1 items-center justify-center gap-1.5 border border-border px-2 py-1.5 text-[11px] text-text-muted transition-colors hover:bg-bg" title="Reset to original machine detections">
					<svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115.36-5.36M20 15a9 9 0 01-15.36 5.36" /></svg>
					Reset
				</button>
			{/if}
		</div>

		<div class="grid grid-cols-3 gap-1 text-center">
			<div class="bg-bg px-1 py-1.5">
				<div class="text-sm font-semibold text-text">{annotatorApi.totalAnnotations}</div>
				<div class="text-[10px] text-text-muted">Total</div>
			</div>
			<div class="bg-bg px-1 py-1.5">
				<div class="text-sm font-semibold text-text">{annotatorApi.seededCount}</div>
				<div class="text-[10px] text-text-muted">Seeded</div>
			</div>
			<div class="bg-bg px-1 py-1.5">
				<div class="text-sm font-semibold text-text">{annotatorApi.manualCount}</div>
				<div class="text-[10px] text-text-muted">Manual</div>
			</div>
		</div>

		{#if annotatorApi.feedback}
			<p class="px-2 py-1.5 text-[11px] {annotatorApi.feedbackTone === 'danger' ? 'bg-primary/8 text-primary' : annotatorApi.feedbackTone === 'success' ? 'bg-success/10 text-success' : 'bg-bg text-text-muted'}">
				{annotatorApi.feedback}
			</p>
		{/if}

		<button
			onclick={annotatorApi.save}
			disabled={annotatorApi.saving || !annotatorApi.isDirty}
			class="flex w-full items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-primary/40 {annotatorApi.saving || !annotatorApi.isDirty ? 'bg-primary/40' : 'bg-primary hover:bg-primary-hover'}"
		>
			<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
			{annotatorApi.saving ? 'Saving...' : 'Save Annotations'}
		</button>
	</div>
</div>

<!--
	Every recording of one motor, newest first: the latest few, the rest on
	request, so the list never scrolls inside the page. A row chooses the
	recording whose load curve is shown; its button deletes it.
-->
<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Button from '$lib/components/ui/Button.svelte';
	import { fmtTime, type Run } from '$lib/settings/stallguard';

	let {
		runs,
		selectedId,
		onselect,
		ondelete
	}: {
		runs: Run[];
		selectedId: string | null;
		onselect: (run: Run) => void;
		ondelete: (run: Run) => void;
	} = $props();

	const SHOWN = 8;
	let showAll = $state(false);
	const shown = $derived(showAll ? runs : runs.slice(0, SHOWN));
</script>

{#if runs.length === 0}
	<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">Nothing recorded yet.</p>
{:else}
	<ul class="divide-y divide-line border-t border-line">
		{#each shown as run (run.id)}
			<li
				class="flex items-start gap-2 pr-2 {selectedId === run.id
					? 'bg-primary-soft'
					: 'hover:bg-hover'}"
			>
				<button
					type="button"
					onclick={() => onselect(run)}
					class="flex min-w-0 flex-1 flex-col gap-0.5 py-(--pad-row) pl-(--pad-panel) text-left text-sm"
				>
					<span class="flex items-center justify-between gap-2">
						<span class="font-mono text-ink">{run.stepper_name ?? '–'}</span>
						<span class="text-ink-muted">{run.source}</span>
					</span>
					<span class="text-ink-muted">{fmtTime(run.started_at)}</span>
					<span class="text-ink-muted">
						{run.sample_count} samples{#if run.sg_min != null}, SG {run.sg_min} to {run.sg_max}{/if}{#if run.suggested_sgthrs != null},
							SGTHRS {run.suggested_sgthrs}{/if}
						{#if run.label}<span class="text-ink"> · {run.label}</span>{/if}
					</span>
				</button>
				<Button
					variant="ghost"
					size="sm"
					icon={Trash2}
					label="Delete run"
					class="mt-2"
					onclick={() => ondelete(run)}
				/>
			</li>
		{/each}
	</ul>
	{#if runs.length > SHOWN}
		<div class="border-t border-line px-(--pad-panel) py-3">
			<Button
				variant="ghost"
				size="sm"
				icon={showAll ? ChevronUp : ChevronDown}
				onclick={() => (showAll = !showAll)}
			>
				{showAll ? `Show the latest ${SHOWN}` : `Show all ${runs.length} runs`}
			</Button>
		</div>
	{/if}
{/if}

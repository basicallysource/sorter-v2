<script lang="ts">
	import Switch from '$lib/components/ui/Switch.svelte';
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	let {
		sectionCount,
		columnEnabled,
		sectionBusyKey,
		pointingKey,
		toggleDisabled,
		pointDisabled,
		onToggleColumn,
		onPointSection
	}: {
		sectionCount: number;
		columnEnabled: (sectionIndex: number) => boolean;
		sectionBusyKey: string | null;
		pointingKey: string | null;
		toggleDisabled: boolean;
		pointDisabled: boolean;
		onToggleColumn: (sectionIndex: number, enabled: boolean) => void;
		onPointSection: (sectionIndex: number) => void;
	} = $props();
</script>

<div class="mb-4 border border-line bg-surface px-4 py-3">
	<div class="mb-2 flex items-center justify-between gap-4">
		<div>
			<div class="text-sm font-medium text-ink">Sections (across all layers)</div>
			<div class="mt-0.5 text-sm text-ink-muted">
				Disable a section here to stop sorting into it on every layer at once, or
				point the chute at it to find it. Per-layer section controls live on each
				layer's section headers below.
			</div>
		</div>
	</div>
	<div class="flex flex-wrap gap-2">
		{#each Array(sectionCount) as _unused, sectionIndex}
			{@const colOn = columnEnabled(sectionIndex)}
			{@const colBusy = sectionBusyKey === `col-${sectionIndex}`}
			<div class="flex items-center gap-2 border border-line {colOn ? 'bg-surface' : 'bg-well'} px-3 py-1.5">
				<span class="text-sm font-semibold {colOn ? 'text-ink' : 'text-ink-muted'}">
					Section {sectionIndex + 1}
				</span>
				<Switch
					checked={colOn}
					label={colOn
						? `Disable section ${sectionIndex + 1} on all layers`
						: `Enable section ${sectionIndex + 1} on all layers`}
					disabled={toggleDisabled}
					onchange={() => onToggleColumn(sectionIndex, !colOn)}
				/>
				<button
					type="button"
					onclick={() => onPointSection(sectionIndex)}
					disabled={pointDisabled}
					class="flex items-center justify-center border border-line bg-surface p-1 text-ink transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
					title="Point chute at section {sectionIndex + 1}"
				>
					{#if pointingKey === `point-${sectionIndex}`}
						<Spinner size={14} />
					{:else}
						<Crosshair size={14} />
					{/if}
				</button>
				{#if colBusy}
					<Spinner size={14} class="text-primary-ink" />
				{/if}
			</div>
		{/each}
	</div>
</div>

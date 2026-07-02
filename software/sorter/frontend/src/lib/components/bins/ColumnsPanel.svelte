<script lang="ts">
	import { ToggleSwitch } from '$lib/components/primitives';
	import { Crosshair, Loader2 } from 'lucide-svelte';

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

<div class="mb-4 border border-[#E2E0DB] bg-surface px-4 py-3">
	<div class="mb-2 flex items-center justify-between gap-4">
		<div>
			<div class="text-sm font-medium text-[#1A1A1A]">Columns (sections across all layers)</div>
			<div class="mt-0.5 text-sm text-[#66635C]">
				Disable a whole column to stop sorting into that section on every layer, or
				point the chute at it to find it.
			</div>
		</div>
	</div>
	<div class="flex flex-wrap gap-2">
		{#each Array(sectionCount) as _unused, sectionIndex}
			{@const colOn = columnEnabled(sectionIndex)}
			{@const colBusy = sectionBusyKey === `col-${sectionIndex}`}
			<div class="flex items-center gap-2 border border-[#E2E0DB] {colOn ? 'bg-white' : 'bg-[#F2F0EB]'} px-3 py-1.5">
				<span class="text-sm font-semibold {colOn ? 'text-[#1A1A1A]' : 'text-[#9A968E]'}">
					Col {sectionIndex + 1}
				</span>
				<ToggleSwitch
					checked={colOn}
					size="sm"
					label={colOn ? `Disable column ${sectionIndex + 1}` : `Enable column ${sectionIndex + 1}`}
					disabled={toggleDisabled}
					onToggle={() => onToggleColumn(sectionIndex, !colOn)}
				/>
				<button
					type="button"
					onclick={() => onPointSection(sectionIndex)}
					disabled={pointDisabled}
					class="flex items-center justify-center border border-[#E2E0DB] bg-white p-1 text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3] disabled:cursor-not-allowed disabled:opacity-50"
					title="Point chute at section {sectionIndex + 1}"
				>
					{#if pointingKey === `point-${sectionIndex}`}
						<Loader2 size={14} class="animate-spin" />
					{:else}
						<Crosshair size={14} />
					{/if}
				</button>
				{#if colBusy}
					<Loader2 size={14} class="animate-spin text-primary" />
				{/if}
			</div>
		{/each}
	</div>
</div>

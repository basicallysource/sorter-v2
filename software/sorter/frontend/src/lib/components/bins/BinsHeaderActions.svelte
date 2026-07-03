<script lang="ts">
	import { ArchiveX, Download, FolderOutput, History, Home } from 'lucide-svelte';

	let {
		csvUrl,
		homing,
		emptyBusy,
		resetBusy,
		disabled,
		onSnapshots,
		onHome,
		onEmptyAll,
		onResetAll
	}: {
		csvUrl: string;
		homing: boolean;
		emptyBusy: boolean;
		resetBusy: boolean;
		disabled: boolean;
		onSnapshots: () => void;
		onHome: () => void;
		onEmptyAll: () => void;
		onResetAll: () => void;
	} = $props();

	const buttonClass =
		'flex items-center gap-2 border border-border bg-surface px-4 py-2 text-sm font-medium text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50';
</script>

<div class="flex items-center gap-3">
	<a href={csvUrl} download class={buttonClass} title="Download current bin contents as CSV">
		<Download size={16} />
		Export CSV
	</a>
	<button
		type="button"
		onclick={onSnapshots}
		class={buttonClass}
		title="View snapshots of previously emptied bin contents"
	>
		<History size={16} />
		Snapshots
	</button>
	<button
		type="button"
		onclick={onHome}
		{disabled}
		class="{buttonClass} {homing ? 'animate-pulse' : ''}"
		title="Home chute (find endstop)"
	>
		<Home size={16} />
		{homing ? 'Homing...' : 'Home Chute'}
	</button>
	<button
		type="button"
		onclick={onEmptyAll}
		{disabled}
		class={buttonClass}
		title="Empty all bins but keep assignments"
	>
		<FolderOutput size={16} />
		{emptyBusy ? 'Emptying…' : 'Empty All Bins'}
	</button>
	<button
		type="button"
		onclick={onResetAll}
		{disabled}
		class={buttonClass}
		title="Reset all bins and remove assignments"
	>
		<ArchiveX size={16} />
		{resetBusy ? 'Resetting…' : 'Reset All Bins'}
	</button>
</div>

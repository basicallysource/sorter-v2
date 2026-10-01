<script lang="ts">
	import ArchiveX from '@lucide/svelte/icons/archive-x';
	import Download from '@lucide/svelte/icons/download';
	import FolderOutput from '@lucide/svelte/icons/folder-output';
	import History from '@lucide/svelte/icons/rotate-ccw-clock';
	import House from '@lucide/svelte/icons/house';
	import Button from '$lib/components/ui/Button.svelte';

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
</script>

<!-- The page's actions, for PageHeader's `actions`. -->
<Button href={csvUrl} download icon={Download}>Export CSV</Button>
<Button icon={History} onclick={onSnapshots}>Snapshots</Button>
<Button icon={House} loading={homing} {disabled} onclick={onHome}>
	{homing ? 'Homing…' : 'Home the chute'}
</Button>
<Button icon={FolderOutput} loading={emptyBusy} {disabled} onclick={onEmptyAll}>
	{emptyBusy ? 'Emptying…' : 'Empty all bins'}
</Button>
<Button icon={ArchiveX} loading={resetBusy} {disabled} onclick={onResetAll}>
	{resetBusy ? 'Resetting…' : 'Reset all bins'}
</Button>

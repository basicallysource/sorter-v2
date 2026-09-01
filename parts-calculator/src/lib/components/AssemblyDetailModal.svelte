<script lang="ts">
	import { ChevronLeft } from 'lucide-svelte';
	import Modal from '$lib/components/Modal.svelte';
	import AssemblyDetail from '$lib/components/AssemblyDetail.svelte';
	import { getAssembly, type Hardware, type Part } from '$lib/filament';

	// Thin modal wrapper around the shared AssemblyDetail view, used by the parts
	// dashboard and the assembly tab so both open the same thing. Parts and
	// hardware are handed back to the caller, which already owns those modals;
	// sub-assemblies are navigated inside this one, since opening a fourth copy of
	// the same modal to see a child box helps nobody.
	let {
		open = $bindable(false),
		id,
		layers,
		onPart,
		onHardware
	}: {
		open?: boolean;
		id: string | null;
		layers: number;
		onPart?: (p: Part) => void;
		onHardware?: (h: Hardware) => void;
	} = $props();

	// The trail below whatever the opener named. Tied to the root it was built
	// from, so pointing the modal at a different assembly drops it without an
	// effect having to notice.
	let trail = $state<string[]>([]);
	let trailRoot = $state<string | null>(null);
	const path = $derived(id ? (trailRoot === id ? [id, ...trail] : [id]) : []);
	const current = $derived(getAssembly(path[path.length - 1] ?? ''));
	const parent = $derived(path.length > 1 ? getAssembly(path[path.length - 2]) : null);

	function go(next: string) {
		if (trailRoot !== id) {
			trailRoot = id;
			trail = [];
		}
		trail = [...trail, next];
	}
</script>

<Modal bind:open title={current?.name} maxW="max-w-3xl">
	{#if current}
		{#if parent}
			<button
				type="button"
				class="flex w-full items-center gap-1 border-b border-border px-4 py-1.5 text-xs font-medium text-text-muted hover:text-primary"
				onclick={() => (trail = trail.slice(0, -1))}
			>
				<ChevronLeft size={13} /> Back to {parent.name}
			</button>
		{/if}
		<AssemblyDetail assembly={current} {layers} {onPart} {onHardware} onAssembly={go} />
	{/if}
</Modal>

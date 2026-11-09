<!--
	Where the pieces no bin takes go. On a chute they fall out of the bottom
	of, a tray under the machine, shown so the operator knows it exists. On a
	chute nothing falls out of, a bin of its own: which one it is, or that none
	is chosen, and the way to choose it.
-->
<script lang="ts">
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { binName } from '$lib/api/bins';
	import type { BinAddress } from '$lib/api/chute';
	import DiscardBinPicker from './DiscardBinPicker.svelte';
	import type { LayerInfo } from './types';

	let {
		base,
		fallsThrough,
		discardBin,
		layers,
		onsaved
	}: {
		base: string;
		fallsThrough: boolean;
		discardBin: BinAddress | null;
		layers: LayerInfo[];
		onsaved: (bin: BinAddress | null) => void | Promise<void>;
	} = $props();
</script>

{#if fallsThrough}
	<Panel title="Discard tray">
		{#snippet actions()}<Badge>Under the chute</Badge>{/snippet}
		<p class="text-sm text-ink-muted">
			Pieces that match no sorting rule, or whose category has no bin, fall through every layer's door
			into the tray under the machine. Empty it by hand when it fills up.
		</p>
	</Panel>
{:else}
	<Panel
		title="Discard bin"
		description={discardBin
			? `${binName(layers, discardBin)} takes the pieces that match no sorting rule, or whose category has no bin. This chute has no tray under it.`
			: 'This chute has no tray under it, so the pieces no bin takes need a bin of their own.'}
	>
		{#if !discardBin}
			<Alert tone="warning" class="mb-4">
				No discard bin is chosen. Until one is, the machine stops when a piece has nowhere to go.
			</Alert>
		{/if}
		<DiscardBinPicker {base} {layers} current={discardBin} {onsaved} />
	</Panel>
{/if}

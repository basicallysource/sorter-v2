<script lang="ts">
	import { Plus, Minus } from 'lucide-svelte';
	import { layerStore, addLayer, removeLastLayer } from '$lib/layers.svelte';

	const count = $derived(layerStore.sizes.length);
</script>

<div class="setup-panel flex flex-wrap items-center justify-between gap-3 p-4">
	<div>
		<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Layers</div>
		<div class="mt-0.5 text-sm text-text-muted">
			Shared with the 3D parts tab — drives every per-layer count.
		</div>
	</div>
	<div class="flex items-center gap-2">
		<button
			class="setup-button-secondary flex h-9 w-9 items-center justify-center disabled:opacity-40"
			onclick={removeLastLayer}
			disabled={count <= 1}
			aria-label="Remove a layer"
		>
			<Minus size={16} />
		</button>
		<span class="w-8 text-center text-lg font-semibold tabular-nums text-text">{count}</span>
		<button
			class="setup-button-secondary flex h-9 w-9 items-center justify-center"
			onclick={() => addLayer()}
			aria-label="Add a layer"
		>
			<Plus size={16} />
		</button>
	</div>
</div>

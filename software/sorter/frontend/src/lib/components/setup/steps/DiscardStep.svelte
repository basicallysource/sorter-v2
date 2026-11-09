<!--
	The discard bin, on a chute nothing falls out of: why it needs one, which
	bin it is, and the way to choose another.
-->
<script lang="ts">
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import DiscardBinPicker from '$lib/components/bins/DiscardBinPicker.svelte';
	import { binName, getBinsLayout, type BinsLayout } from '$lib/api/bins';
	import { errorMessage } from '$lib/api/http';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	const chute = $derived(flow.summary!.config.chute);

	let layout = $state<BinsLayout | null>(null);
	let loadError = $state<string | null>(null);

	async function load() {
		loadError = null;
		try {
			layout = await getBinsLayout(flow.base);
		} catch (e) {
			loadError = errorMessage(e, 'The bins did not load.');
		}
	}

	async function saved() {
		await Promise.all([load(), flow.reload()]);
	}

	$effect(() => {
		void load();
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	<Alert tone="info">
		The {chute.variant_label} has no tray under it: its bottom door is shut, so the pieces no other bin
		takes need a bin of their own.
	</Alert>
	{#if loadError}
		<Alert tone="danger" title="The bins did not load">
			{loadError}
			{#snippet actions()}
				<Button size="sm" icon={RotateCcw} onclick={() => void load()}>Try again</Button>
			{/snippet}
		</Alert>
	{:else if !layout}
		<Panel>
			<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={16} /> Loading the bins</p>
		</Panel>
	{:else}
		<Panel
			title="Which bin it is"
			description={layout.discard_bin
				? `${binName(layout.layers, layout.discard_bin)} takes the pieces no other bin takes.`
				: 'None is chosen yet. Until one is, the machine stops when a piece has nowhere to go.'}
		>
			<DiscardBinPicker base={flow.base} layers={layout.layers} current={layout.discard_bin} onsaved={saved} />
		</Panel>
	{/if}
</div>

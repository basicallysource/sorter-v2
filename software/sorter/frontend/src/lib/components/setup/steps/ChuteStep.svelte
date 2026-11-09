<!--
	Which kind of chute this machine has. A board made for one kind settles it:
	the other kind is shown as not this machine's. Otherwise the person picks
	one, and it is saved at once. Hardware that started as the other kind
	keeps it until it is started again, and the step says so.
-->
<script lang="ts">
	import Power from '@lucide/svelte/icons/power';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import PictureChoice from '$lib/components/ui/PictureChoice.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { saveChuteVariant } from '$lib/api/chute';
	import { errorMessage } from '$lib/api/http';
	import { stopHardware } from '$lib/api/system';
	import { chutePictures } from '$lib/chute/pictures';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	const chute = $derived(flow.summary!.config.chute);
	// The kind a found board is made for, if any board is made for one.
	const boardKind = $derived(flow.summary!.discovery.boards.find((board) => board.chute_variant)?.chute_variant ?? null);
	const boardKindLabel = $derived(chute.variants.find((variant) => variant.key === boardKind)?.label ?? null);
	const settled = $derived(boardKind !== null && chute.variant === boardKind);

	// The tile shown chosen: what is saved, or what is being saved.
	const savedKind = $derived(chute.variant_saved || settled ? chute.variant : null);
	let picked = $state<string | null>(null);
	$effect(() => {
		picked = savedKind;
	});

	let saving = $state(false);
	let error = $state<string | null>(null);
	let message = $state<string | null>(null);
	let restartNeeded = $state(false);
	let restarting = $state(false);
	let restartError = $state<string | null>(null);

	const options = $derived(
		chute.variants.map((variant) => ({
			value: variant.key,
			label: variant.label,
			help: variant.summary,
			picture: chutePictures(variant.key)?.closeUp ?? null,
			disabled: boardKind !== null && variant.key !== boardKind,
			note:
				boardKind !== null && variant.key !== boardKind
					? `Not this machine's: its control board is made for the ${boardKindLabel}.`
					: undefined
		}))
	);

	async function choose(key: string) {
		if (key === chute.variant && chute.variant_saved) return;
		saving = true;
		error = null;
		message = null;
		try {
			const result = await saveChuteVariant(flow.base, key);
			restartNeeded = result.restart_needed;
			message = result.restart_needed ? null : result.message;
			await flow.reload();
		} catch (e) {
			picked = savedKind;
			error = errorMessage(e, 'The chute was not saved.');
		} finally {
			saving = false;
		}
	}

	// The running hardware keeps the kind it started as: stop it and start it again.
	async function restart() {
		restarting = true;
		restartError = null;
		try {
			await stopHardware(flow.base);
			await flow.startHardware();
			if (flow.startError) throw new Error(flow.startError);
			restartNeeded = false;
		} catch (e) {
			restartError = errorMessage(e, 'The motors did not start again.');
		} finally {
			restarting = false;
		}
	}
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if boardKind && settled}
		<Alert tone="success" title="This board is made for the {boardKindLabel}">
			Its kind of chute is settled by the board, so there is nothing to choose.
		</Alert>
	{:else if boardKind && !settled}
		<Alert tone="warning" title="This board is made for the {boardKindLabel}">
			The {chute.variant_label} is saved for this machine, which this board cannot drive.
			{#snippet actions()}
				<Button size="sm" loading={saving} onclick={() => void choose(boardKind)}>
					Use the {boardKindLabel}
				</Button>
			{/snippet}
		</Alert>
	{/if}

	<Panel
		title="Which chute this machine has"
		description={boardKind
			? undefined
			: 'Look at the top of the chute, where the wiring to the doors turns with it.'}
	>
		<PictureChoice
			name="chute-kind"
			label="Which chute this machine has"
			bind:value={picked}
			{options}
			onchange={(key) => void choose(key)}
		/>
		{#if saving}
			<p class="mt-3 flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Saving</p>
		{:else if error}
			<Alert tone="danger" class="mt-3">{error}</Alert>
		{:else if message && !boardKind}
			<p class="mt-3 text-sm text-success-ink">{message}</p>
		{/if}
	</Panel>

	{#if restartNeeded}
		<Alert tone="warning" title="Start the motors again">
			They were started for the other chute and keep to it until they start again.
			{#if restartError}<p class="mt-1 text-danger-ink">{restartError}</p>{/if}
			{#snippet actions()}
				<Button size="sm" icon={Power} loading={restarting} onclick={() => void restart()}>
					Start them again
				</Button>
			{/snippet}
		</Alert>
	{/if}
</div>

<!--
	How many turns of its motor one turn of the chute takes, and the button
	that measures it on a chute that homes on a magnet: home, once round to the
	magnet again, save the ratio, home again. A panel of its own, used by the
	setup flow and Settings › Chute.
-->
<script lang="ts">
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { measureChuteTurn, type ChuteSettings } from '$lib/api/chute';
	import { errorMessage } from '$lib/api/http';

	let {
		base,
		chute,
		// The motors are on, so the chute can turn.
		ready,
		onmeasured
	}: {
		base: string;
		chute: ChuteSettings;
		ready: boolean;
		onmeasured?: (settings: ChuteSettings) => void;
	} = $props();

	let measuring = $state(false);
	let error = $state<string | null>(null);
	let message = $state<string | null>(null);

	async function measure() {
		measuring = true;
		error = null;
		message = null;
		try {
			const result = await measureChuteTurn(base);
			message = result.homed ? result.message : `${result.message} It did not find home again afterwards: find home before sorting.`;
			onmeasured?.(result.settings);
		} catch (e) {
			error = errorMessage(e, 'The turn was not measured.');
		} finally {
			measuring = false;
		}
	}
</script>

<Panel
	title="One turn of the chute"
	description="The chute turns once round from its magnet back to it, slowly, and counts its motor's turns. Keep hands clear while it turns."
>
	<p class="text-sm text-ink">
		<span class="num">{chute.gear_ratio.toFixed(3)}</span> turns of the motor make one turn of the chute,
		<span class="text-ink-muted">
			{chute.gear_ratio_measured ? 'as measured on this machine.' : 'as the chute is built. It has not been measured here.'}
		</span>
	</p>
	{#if error}
		<Alert tone="danger" class="mt-3">{error}</Alert>
	{:else if message}
		<Alert tone="success" class="mt-3">{message}</Alert>
	{/if}
	{#snippet footer()}
		{#if !ready}<span class="mr-auto text-sm text-ink-muted">Power on the motors first.</span>{/if}
		<Button
			variant={chute.gear_ratio_measured ? 'secondary' : 'primary'}
			icon={RotateCw}
			loading={measuring}
			disabled={!ready}
			onclick={() => void measure()}
		>
			{chute.gear_ratio_measured ? 'Measure it again' : 'Measure a turn'}
		</Button>
	{/snippet}
</Panel>

<!--
	Whether the motors are powered, for a setup step that needs them: a notice
	with the button that powers them while they are off, their progress while
	they start, and the fault, with a way to try again, when they could not.
	Nothing shows once they are on.
-->
<script lang="ts">
	import Power from '@lucide/svelte/icons/power';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let {
		flow,
		// What powering them unlocks on this step.
		unlocks
	}: { flow: SetupFlow; unlocks: string } = $props();
</script>

{#if flow.startError}
	<Alert tone="danger" title="The motors did not power on">
		{flow.startError}
		{#snippet actions()}
			<Button size="sm" icon={RotateCcw} loading={flow.starting} onclick={() => void flow.startHardware()}>
				Try again
			</Button>
		{/snippet}
	</Alert>
{:else if flow.hardwareBusy}
	<Alert tone="info" title="Powering on the motors">
		<span class="inline-flex items-center gap-2">
			<Spinner size={14} />
			{(flow.homingStep ?? 'Finding the boards').replace(/[.…\s]+$/, '')}. {unlocks}
		</span>
	</Alert>
{:else if flow.hardwareState === 'error'}
	<Alert tone="danger" title="The hardware stopped with a fault">
		{flow.hardwareError ?? 'It did not say why.'} Check the boards' power and cables, then try again.
		{#snippet actions()}
			<Button size="sm" icon={RotateCcw} onclick={() => void flow.startHardware()}>Try again</Button>
		{/snippet}
	</Alert>
{:else if !flow.hardwareUp}
	<Alert tone="info" title="The motors are off">
		{unlocks}
		{#snippet actions()}
			<Button size="sm" icon={Power} onclick={() => void flow.startHardware()}>Power on the motors</Button>
		{/snippet}
	</Alert>
{/if}

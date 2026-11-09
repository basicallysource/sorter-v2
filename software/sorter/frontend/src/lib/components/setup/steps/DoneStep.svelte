<!--
	The end of the setup: every step and whether it is done, with the way back
	to one that is not, and homing the machine so it is ready for a first run.
	The footer's button opens the dashboard.
-->
<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import House from '@lucide/svelte/icons/house';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { errorMessage } from '$lib/api/http';
	import { homeMachine } from '$lib/api/system';
	import type { SetupFlow } from '$lib/setup/flow.svelte';
	import { stepsFor, type StepId } from '$lib/setup/steps';

	let {
		flow,
		ongoto
	}: { flow: SetupFlow; onnext: () => void; ongoto: (id: StepId) => void } = $props();

	const ctx = $derived(flow.context);
	const rows = $derived(
		ctx ? stepsFor(ctx).filter((step) => step.id !== 'done').map((step) => ({ step, done: step.status(ctx).done })) : []
	);
	const left = $derived(rows.filter((row) => !row.done).length);
	const ready = $derived(flow.hardwareState === 'ready');

	let homing = $state(false);
	let homeError = $state<string | null>(null);

	async function home() {
		homing = true;
		homeError = null;
		try {
			await homeMachine(flow.base);
		} catch (e) {
			homeError = errorMessage(e, 'The machine did not start homing.');
		} finally {
			homing = false;
		}
	}
</script>

<div class="flex flex-col gap-(--gap-panels)">
	<Panel title="The setup" flush>
		{#snippet actions()}
			<Badge tone={left === 0 ? 'success' : 'primary'}>{left === 0 ? 'All done' : `${left} left`}</Badge>
		{/snippet}
		<ul class="divide-y divide-line">
			{#each rows as row (row.step.id)}
				<li class="flex items-center gap-3 px-(--pad-panel) py-2.5 text-sm">
					<span
						class="flex size-6 shrink-0 items-center justify-center rounded-badge {row.done
							? 'bg-success-soft text-success-ink'
							: 'bg-well text-ink-muted'}"
						aria-hidden="true"
					>
						{#if row.done}<Check size={14} />{/if}
					</span>
					<span class="flex min-h-(--size-control-sm) min-w-0 flex-1 items-center {row.done ? 'text-ink' : 'text-ink-muted'}">
						{row.step.short ?? row.step.title}
						<span class="sr-only">{row.done ? ', done' : ', not done'}</span>
					</span>
					{#if !row.done}
						<Button size="sm" variant="ghost" onclick={() => ongoto(row.step.id)}>Go to it</Button>
					{/if}
				</li>
			{/each}
		</ul>
	</Panel>

	<Panel
		title="Ready to sort"
		description="Homing turns every motor to its home. After that the dashboard can start a first run."
	>
		{#if ready}
			<p class="text-sm text-success-ink">The machine is homed and ready.</p>
		{:else if flow.hardwareState === 'homing'}
			<p class="flex items-center gap-2 text-sm text-ink-muted">
				<Spinner size={14} />
				{flow.homingStep ?? 'Homing'}
			</p>
		{:else if flow.hardwareState === 'error'}
			<Alert tone="danger" title="Homing stopped with a fault">{flow.hardwareError ?? 'It did not say why.'}</Alert>
		{/if}
		{#if homeError}<Alert tone="danger" class="mt-3">{homeError}</Alert>{/if}
		{#snippet footer()}
			<Button
				variant={ready ? 'secondary' : 'primary'}
				icon={House}
				loading={homing || flow.hardwareState === 'homing'}
				onclick={() => void home()}
			>
				{ready ? 'Home it again' : 'Home the machine'}
			</Button>
		{/snippet}
	</Panel>
</div>

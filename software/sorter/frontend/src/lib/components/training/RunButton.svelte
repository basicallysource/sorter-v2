<!--
	Start run, or End run while one is open. A run collects every piece until
	it is ended, across pauses; it starts with the chosen color.
-->
<script lang="ts">
	import Play from '@lucide/svelte/icons/play';
	import Square from '@lucide/svelte/icons/square';
	import Button from '$lib/components/ui/Button.svelte';
	import { endRun, startRun, type TrainingState } from '$lib/training/api';

	let {
		base,
		training,
		onchange
	}: {
		base: string;
		training: TrainingState;
		onchange: (next: TrainingState) => void;
	} = $props();

	let busy = $state(false);
	let error = $state<string | null>(null);

	const run = $derived(training.current_run);
	const ready = $derived(training.config.enabled && training.config.color_ids.length > 0);

	async function act() {
		busy = true;
		error = null;
		try {
			onchange(run ? await endRun(base, run.id) : await startRun(base));
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<span class="inline-flex flex-col items-end gap-1">
	{#if run}
		<Button size="sm" icon={Square} loading={busy} onclick={act}>End run</Button>
	{:else}
		<Button
			size="sm"
			variant="primary"
			icon={Play}
			loading={busy}
			disabled={!ready}
			title={ready ? undefined : 'Pick a color first'}
			onclick={act}
		>
			Start run
		</Button>
	{/if}
	{#if error}<span class="text-sm text-danger-ink">{error}</span>{/if}
</span>

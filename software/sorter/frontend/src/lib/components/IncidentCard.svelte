<script lang="ts" module>
	/*
		The open incident, as the backend describes it (incidents.describe):
		what happened, one line of what to do, and the buttons that do it.
	*/
	export type IncidentCardData = {
		kind: string;
		title: string;
		subject: string;
		todo: string;
		actions: { key: string; label: string }[];
		// A recovery procedure working on it (backend recovery/): which step of
		// how many, what that step does, and how it went.
		recovery?: {
			title: string;
			step: number;
			steps: number;
			doing: string;
			state: 'running' | 'freed' | 'gave up' | 'stopped';
		};
	};
</script>

<script lang="ts">
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ProgressBar from '$lib/components/ui/ProgressBar.svelte';

	let { card, baseUrl }: { card: IncidentCardData; baseUrl: string } = $props();

	let pending = $state<string | null>(null);
	let error = $state<string | null>(null);

	async function act(action: string) {
		if (pending) return;
		pending = action;
		error = null;
		try {
			const res = await fetch(`${baseUrl}/api/incidents/action`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action })
			});
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				error = typeof body.detail === 'string' ? body.detail : 'That did not work.';
			}
		} catch {
			error = 'The machine did not answer.';
		} finally {
			pending = null;
		}
	}
</script>

<Alert
	tone="warning"
	title={card.subject ? `${card.title} · ${card.subject}` : card.title}
	class="shrink-0 max-lg:order-first"
>
	<p>{card.todo}</p>
	{#if card.recovery}
		{@const recovery = card.recovery}
		<div class="mt-2 flex flex-col gap-1.5">
			<ProgressBar
				value={recovery.state === 'running' ? recovery.step - 1 : recovery.steps}
				max={recovery.steps}
				label={recovery.title}
				tone={recovery.state === 'running' ? 'primary' : 'warning'}
			/>
			{#if recovery.state === 'running'}
				<p class="text-ink-muted">Step {recovery.step} of {recovery.steps}: {recovery.doing}</p>
			{:else if recovery.state === 'stopped'}
				<p class="text-ink-muted">Stopped at step {recovery.step} of {recovery.steps}.</p>
			{:else if recovery.state === 'gave up'}
				<p class="text-ink-muted">Tried all {recovery.steps} steps; it is still stuck.</p>
			{/if}
		</div>
	{/if}
	{#if error}
		<p class="mt-1.5 text-danger-ink">{error}</p>
	{/if}
	{#snippet actions()}
		{#each card.actions as action, i (action.key)}
			<Button
				variant={i === 0 ? 'primary' : 'secondary'}
				loading={pending === action.key}
				disabled={pending !== null}
				onclick={() => act(action.key)}
			>
				{action.label}
			</Button>
		{/each}
	{/snippet}
</Alert>

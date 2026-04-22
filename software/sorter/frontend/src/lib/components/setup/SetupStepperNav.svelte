<script lang="ts">
	import { Check, Pencil } from 'lucide-svelte';

	type WizardStepDefinition<Id extends string = string> = {
		id: Id;
		title: string;
		kicker: string;
		description: string;
		requiresManualConfirm: boolean;
	};

	type StepStatus = 'current' | 'done' | 'locked' | 'ready';

	let {
		steps,
		getStatus,
		canOpenStep,
		onSelect
	}: {
		steps: WizardStepDefinition[];
		getStatus: (stepId: string) => StepStatus;
		canOpenStep: (stepId: string) => boolean;
		onSelect: (stepId: string) => void;
	} = $props();
</script>

<ol class="flex w-full items-start">
	{#each steps as step, index}
		{@const status = getStatus(step.id)}
		{@const isFirst = index === 0}
		{@const isLast = index === steps.length - 1}
		{@const prevStatus = index > 0 ? getStatus(steps[index - 1].id) : null}
		<li class="relative flex min-w-0 flex-1 flex-col items-center">
			{#if !isFirst}
				<div
					class={`absolute left-0 top-5 -ml-px h-0.5 w-1/2 ${
						prevStatus === 'done' ? 'bg-success' : 'bg-border'
					}`}
				></div>
			{/if}
			{#if !isLast}
				<div
					class={`absolute right-0 top-5 -mr-px h-0.5 w-1/2 ${
						status === 'done' ? 'bg-success' : 'bg-border'
					}`}
				></div>
			{/if}
			<button
				type="button"
				onclick={() => onSelect(step.id)}
				disabled={!canOpenStep(step.id)}
				aria-label={step.title}
				class={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${
					status === 'done'
						? 'border-success bg-success text-white hover:bg-success/90'
						: status === 'current'
							? 'border-success bg-white text-success'
							: 'border-border bg-white text-text-muted'
				}`}
			>
				{#if status === 'done'}
					<Check size={18} strokeWidth={3} />
				{:else if status === 'current'}
					<Pencil size={15} strokeWidth={2.5} />
				{:else}
					{index + 1}
				{/if}
			</button>
			<div
				class={`mt-2 px-1 text-center text-xs font-medium leading-4 ${
					status === 'done' || status === 'current' ? 'text-success' : 'text-text-muted'
				}`}
			>
				{step.title}
			</div>
		</li>
	{/each}
</ol>

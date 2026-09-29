<script lang="ts">
	import Check from '@lucide/svelte/icons/check';

	type WizardStepDefinition<Id extends string = string> = {
		id: Id;
		title: string;
		description: string;
		requiresManualConfirm: boolean;
	};

	type StepStatus = 'current' | 'done' | 'ready';

	let {
		steps,
		getStatus,
		onSelect
	}: {
		steps: WizardStepDefinition[];
		getStatus: (stepId: string) => StepStatus;
		onSelect: (stepId: string) => void;
	} = $props();
</script>

<!-- The steps in a row on the surface, joined by a line that turns green as
     they are done; below md only the numbers show (the page's title names the
     current one). -->
<nav aria-label="Setup steps" class="rounded-panel bg-surface px-2 py-4 sm:px-(--pad-panel)">
	<ol class="flex items-start">
		{#each steps as step, index (step.id)}
			{@const status = getStatus(step.id)}
			<li class="relative flex min-w-0 flex-1 flex-col items-center gap-2">
				{#if index > 0}
					<span
						class="absolute top-4 right-[calc(50%+1.25rem)] left-0 h-px {getStatus(steps[index - 1].id) ===
						'done'
							? 'bg-success'
							: 'bg-line'}"
					></span>
				{/if}
				{#if index < steps.length - 1}
					<span
						class="absolute top-4 right-0 left-[calc(50%+1.25rem)] h-px {status === 'done'
							? 'bg-success'
							: 'bg-line'}"
					></span>
				{/if}
				<button
					type="button"
					onclick={() => onSelect(step.id)}
					aria-label={step.title}
					aria-current={status === 'current' ? 'step' : undefined}
					class="relative flex size-8 items-center justify-center rounded-badge text-sm font-medium transition-colors {status ===
					'done'
						? 'bg-success-soft text-success-ink'
						: status === 'current'
							? 'bg-primary-soft text-primary-ink'
							: 'bg-well text-ink-muted hover:bg-hover'}"
				>
					{#if status === 'done'}<Check size={16} />{:else}{index + 1}{/if}
				</button>
				<span
					class="px-1 text-center text-sm max-md:sr-only {status === 'current'
						? 'font-medium text-ink'
						: 'text-ink-muted'}"
				>
					{step.title}
				</span>
			</li>
		{/each}
	</ol>
</nav>

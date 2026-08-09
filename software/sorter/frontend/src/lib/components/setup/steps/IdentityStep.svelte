<script lang="ts">
	import { Shuffle } from 'lucide-svelte';

	let {
		machineId,
		nicknameDraft = $bindable(),
		nameError,
		nameStatus,
		onSuggestAnother
	}: {
		machineId: string;
		nicknameDraft: string;
		nameError: string | null;
		nameStatus: string;
		onSuggestAnother: () => void;
	} = $props();

	const MACHINE_NAME_INPUT_ID = 'setup-machine-name';
</script>

<div class="flex flex-col gap-4">
	<div class="text-xs text-text-muted">
		Machine ID:
		<span class="font-mono text-text">{machineId || '—'}</span>
	</div>
	<div>
		<label for={MACHINE_NAME_INPUT_ID} class="mb-2 block text-sm font-medium text-text">
			Machine name
		</label>
		<div class="flex items-stretch gap-2">
			<input
				id={MACHINE_NAME_INPUT_ID}
				type="text"
				bind:value={nicknameDraft}
				placeholder="e.g. Sorting Bench A"
				class="setup-control min-w-0 flex-1 px-3 py-2 text-sm text-text"
			/>
			<button
				type="button"
				onclick={onSuggestAnother}
				class="setup-control flex shrink-0 items-center gap-2 px-3 text-sm whitespace-nowrap text-text-muted transition-colors hover:text-text"
			>
				<Shuffle class="h-4 w-4" />
				Generate New Name
			</button>
		</div>
	</div>
	{#if nameError}
		<div class="text-sm text-danger">{nameError}</div>
	{:else if nameStatus}
		<div class="text-sm text-success">{nameStatus}</div>
	{/if}
</div>

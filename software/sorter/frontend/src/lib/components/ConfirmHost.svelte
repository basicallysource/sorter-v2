<script lang="ts">
	// The one place a confirmation is drawn (see $lib/confirm.svelte.ts), mounted once in the root layout.
	import Button from '$lib/components/ui/Button.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import { confirmation } from '$lib/confirm.svelte';

	const current = $derived(confirmation.current);
</script>

<Modal
	open={current !== null}
	title={current?.title ?? ''}
	size="sm"
	onclose={() => confirmation.settle(false)}
>
	<p class="whitespace-pre-line">{current?.message}</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => confirmation.settle(false)}>Cancel</Button>
		<Button variant={current?.danger ? 'danger' : 'primary'} onclick={() => confirmation.settle(true)}>
			{current?.action}
		</Button>
	{/snippet}
</Modal>

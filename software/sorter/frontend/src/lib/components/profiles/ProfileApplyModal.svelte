<script lang="ts">
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import type { PendingProfileApply } from '$lib/sorting-profiles/types';

	type Props = {
		open: boolean;
		pending: PendingProfileApply | null;
		onConfirm: () => void;
		onCancel: () => void;
	};

	let { open = $bindable(), pending, onConfirm, onCancel }: Props = $props();
</script>

<Modal bind:open title="Activate the profile on this machine">
	{#if pending}
		<div class="flex flex-col gap-4">
			<Alert tone="warning" title="Empty all physical bins first.">
				Activating a different sorting profile resets every learned bin assignment on this machine.
				After that, bins are assigned again as parts are sorted.
			</Alert>
			<KeyValue
				items={[
					{ label: 'Target', value: pending.target_name },
					{ label: 'Profile', value: pending.profile_name },
					{
						label: 'Version',
						value: `v${pending.version_number ?? '?'}${pending.version_label ? ` - ${pending.version_label}` : ''}`
					}
				]}
			/>
		</div>
	{/if}
	{#snippet footer()}
		<Button variant="ghost" onclick={onCancel}>Cancel</Button>
		<Button variant="primary" onclick={onConfirm}>Empty the bins and activate</Button>
	{/snippet}
</Modal>

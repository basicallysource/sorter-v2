<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import type { PendingProfileApply } from '$lib/sorting-profiles/types';

	type Props = {
		open: boolean;
		pending: PendingProfileApply | null;
		onConfirm: () => void;
		onCancel: () => void;
	};

	let { open = $bindable(), pending, onConfirm, onCancel }: Props = $props();
</script>

<Modal bind:open title="Activate Profile on Machine">
	{#if pending}
		<div class="space-y-4">
			<div class="border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-text">
				<div class="font-medium text-text">Please empty all physical bins first.</div>
				<div class="mt-2 text-text-muted">
					Activating a different sorting profile will reset all learned bin assignments on this
					machine. After that, bins will be assigned again as parts are sorted.
				</div>
			</div>

			<div class="grid gap-2 border border-border bg-surface px-4 py-3 text-sm text-text-muted">
				<div>Target: <span class="font-medium text-text">{pending.target_name}</span></div>
				<div>Profile: <span class="font-medium text-text">{pending.profile_name}</span></div>
				<div>
					Version:
					<span class="font-medium text-text">
						v{pending.version_number ?? '?'}
						{pending.version_label ? ` - ${pending.version_label}` : ''}
					</span>
				</div>
			</div>

			<div class="flex flex-wrap justify-end gap-2">
				<button
					type="button"
					onclick={onCancel}
					class="border border-border px-3 py-2 text-sm text-text transition-colors hover:bg-bg"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={onConfirm}
					class="border border-primary bg-primary px-3 py-2 text-sm font-medium text-primary-contrast transition-colors hover:bg-primary-hover"
				>
					Empty Bins and Activate
				</button>
			</div>
		</div>
	{/if}
</Modal>

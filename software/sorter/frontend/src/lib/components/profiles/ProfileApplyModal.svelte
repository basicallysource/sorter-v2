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
			<div class="border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-ink">
				<div class="font-medium text-ink">Please empty all physical bins first.</div>
				<div class="mt-2 text-ink-muted">
					Activating a different sorting profile will reset all learned bin assignments on this
					machine. After that, bins will be assigned again as parts are sorted.
				</div>
			</div>

			<div class="grid gap-2 border border-line bg-surface px-4 py-3 text-sm text-ink-muted">
				<div>Target: <span class="font-medium text-ink">{pending.target_name}</span></div>
				<div>Profile: <span class="font-medium text-ink">{pending.profile_name}</span></div>
				<div>
					Version:
					<span class="font-medium text-ink">
						v{pending.version_number ?? '?'}
						{pending.version_label ? ` - ${pending.version_label}` : ''}
					</span>
				</div>
			</div>

			<div class="flex flex-wrap justify-end gap-2">
				<button
					type="button"
					onclick={onCancel}
					class="border border-line px-3 py-2 text-sm text-ink transition-colors hover:bg-hover"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={onConfirm}
					class="border border-primary bg-primary px-3 py-2 text-sm font-medium text-on-primary transition-colors hover:bg-primary-hover"
				>
					Empty Bins and Activate
				</button>
			</div>
		</div>
	{/if}
</Modal>

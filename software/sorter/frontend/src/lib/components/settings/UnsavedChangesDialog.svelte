<script lang="ts">
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import type { UnsavedGuard } from '$lib/settings/unsavedChanges.svelte';

	// Renders only while the guard has a navigation held. Three outcomes, because
	// the two-button browser confirm forces "discard" and "cancel" to share a
	// button and quietly loses work.
	let { guard }: { guard: UnsavedGuard } = $props();
</script>

{#if guard.promptUrl}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
		role="dialog"
		aria-modal="true"
		aria-labelledby="unsaved-changes-title"
	>
		<div class="w-full max-w-md border border-line bg-surface p-5">
			<div id="unsaved-changes-title" class="text-lg font-semibold text-ink">
				You have unsaved changes
			</div>
			<div class="mt-2 text-sm text-ink-muted">
				Leaving this page will discard the edits you have not saved yet.
			</div>

			{#if guard.error}
				<div class="mt-4">
					<Alert tone="danger">{guard.error}</Alert>
				</div>
			{/if}

			<div class="mt-5 flex flex-wrap gap-3">
				<Button variant="primary" onclick={() => guard.saveAndLeave()} loading={guard.busy}>
					Save and leave
				</Button>
				<Button variant="danger" onclick={() => guard.discardAndLeave()} disabled={guard.busy}>
					Discard changes
				</Button>
				<Button variant="secondary" onclick={() => guard.stay()} disabled={guard.busy}>
					Stay on page
				</Button>
			</div>
		</div>
	</div>
{/if}

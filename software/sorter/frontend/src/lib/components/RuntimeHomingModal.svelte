<script lang="ts">
	import { Loader2, AlertTriangle, Home } from 'lucide-svelte';
	import Modal from '$lib/components/Modal.svelte';

	let {
		open,
		hardwareState,
		hardwareError,
		homingStep,
		homePending,
		onHome,
		onCancel
	}: {
		open: boolean;
		hardwareState: string;
		hardwareError: string | null;
		homingStep: string | null;
		homePending: boolean;
		onHome: () => void;
		onCancel: () => void;
	} = $props();

	const homing = $derived(homePending || hardwareState === 'homing' || hardwareState === 'initializing');
	const ready = $derived(hardwareState === 'ready');
	const errored = $derived(hardwareState === 'error');
</script>

<Modal {open} title="Home the machine" on:close={onCancel}>
	<div class="flex flex-col gap-4 px-1 py-1">
		<p class="text-sm text-text-muted">
			The machine needs to home its axes before pieces can be sorted. The setup wizard only
			describes the hardware — homing happens here, right before a run.
		</p>

		{#if ready}
			<div class="border border-success bg-success/10 px-4 py-3 text-sm font-medium text-success">
				Hardware is homed and ready. You can close this dialog.
			</div>
		{:else if homing}
			<div class="flex items-center gap-3 border border-warning bg-warning/10 px-4 py-3 text-sm text-warning-dark">
				<Loader2 size={18} class="animate-spin shrink-0" />
				<div class="flex flex-col">
					<span class="font-medium">Homing in progress…</span>
					<span class="text-xs text-warning-dark/80">
						{homingStep ?? 'Initializing hardware'} — please don't interrupt the axes.
					</span>
				</div>
			</div>
		{:else if errored}
			<div class="flex items-start gap-3 border border-danger bg-danger/10 px-4 py-3 text-sm text-danger">
				<AlertTriangle size={18} class="mt-0.5 shrink-0" />
				<div class="flex flex-col gap-1">
					<span class="font-medium">Homing failed</span>
					{#if hardwareError}
						<span class="text-xs text-danger/80">{hardwareError}</span>
					{/if}
					<span class="text-xs text-text-muted">Check the wiring and endstops, then retry.</span>
				</div>
			</div>
		{:else}
			<div class="border border-border bg-bg px-4 py-3 text-sm text-text">
				<div class="font-medium">Hardware on standby.</div>
				<div class="mt-1 text-sm text-text-muted">
					Press Home to power on the steppers and home all axes. Cancel returns to the dashboard;
					you can re-open this dialog at any time from the sidebar.
				</div>
			</div>
		{/if}

		<div class="flex items-center justify-end gap-2 border-t border-border pt-4">
			<button
				type="button"
				onclick={onCancel}
				class="setup-button-secondary px-4 py-2 text-sm text-text transition-colors"
			>
				{ready ? 'Close' : 'Cancel'}
			</button>
			{#if !ready}
				<button
					type="button"
					onclick={onHome}
					disabled={homing}
					class="inline-flex items-center gap-2 border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
				>
					<Home size={14} />
					{homing ? 'Homing…' : errored ? 'Retry' : 'Home'}
				</button>
			{/if}
		</div>
	</div>
</Modal>

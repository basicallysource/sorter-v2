<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	type HiveSetupTarget = {
		id: string;
		name: string;
		url: string;
		machine_id: string | null;
		enabled: boolean;
	};

	let {
		hiveLoading,
		officialHiveTarget,
		defaultHiveUrl,
		hiveUrl = $bindable(),
		hiveConnecting,
		hiveError,
		hiveStatus,
		machineDisplayName,
		onConnect,
		onSkip
	}: {
		hiveLoading: boolean;
		officialHiveTarget: HiveSetupTarget | null;
		defaultHiveUrl: string;
		hiveUrl: string;
		hiveConnecting: boolean;
		hiveError: string | null;
		hiveStatus: string | null;
		machineDisplayName: string;
		onConnect: () => void;
		onSkip: () => void;
	} = $props();
</script>

<div class="flex flex-col gap-4">
	{#if hiveLoading}
		<div class="setup-panel flex items-center gap-2 px-4 py-3 text-sm text-ink-muted">
			<Spinner size={14} />
			Checking current Hive configuration…
		</div>
	{:else if officialHiveTarget}
		<div
			class="border border-success/40 bg-success-soft px-4 py-3"
		>
			<div class="flex items-start gap-3">
				<div
					class="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-success text-white"
				>
					<Check size={14} strokeWidth={3} />
				</div>
				<div class="flex min-w-0 flex-1 flex-col gap-1">
					<div
						class="text-xs font-semibold text-success-ink"
					>
						Connected to Hive
					</div>
					<div class="text-sm leading-relaxed text-ink">
						This sorter is registered with
						<span class="font-mono">{officialHiveTarget.url}</span>.
					</div>
					{#if officialHiveTarget.machine_id}
						<div class="text-xs text-ink-muted">
							Machine ID
							<span class="font-mono text-ink">{officialHiveTarget.machine_id}</span>
						</div>
					{/if}
				</div>
			</div>
		</div>
		<div class="text-xs text-ink-muted">
			You can manage this connection later under Settings › Hive. Click Continue to finish the
			setup wizard.
		</div>
	{:else}
		<div class="setup-panel flex flex-col gap-2 px-4 py-3">
			<div class="text-xs font-semibold text-ink-muted">
				Hive server
			</div>
			<input
				type="url"
				bind:value={hiveUrl}
				placeholder={defaultHiveUrl}
				class="setup-control px-3 py-2 font-mono text-sm text-ink"
				disabled={hiveConnecting}
			/>
			<div class="text-xs text-ink-muted">
				Uses the official community platform by default. You can enter a local or custom Hive
				URL here for development.
			</div>
		</div>

		<div class="setup-panel flex flex-col gap-1 px-4 py-3">
			<div class="text-xs font-semibold text-ink-muted">
				Machine name
			</div>
			<div class="text-sm text-ink">{machineDisplayName}</div>
			<div class="text-xs text-ink-muted">
				This is how your sorter will appear in Hive. Change it in Step 1 if needed.
			</div>
		</div>

		<div class="text-sm leading-relaxed text-ink-muted">
			Continuing will send you to the Hive server above. Sign in there (or create an
			account first) and confirm the machine name — Hive will bring you straight back
			here and finish the link. No password is ever stored on this Sorter.
		</div>

		<div class="flex flex-wrap items-center gap-2">
			<button
				type="button"
				onclick={onConnect}
				disabled={hiveConnecting || !hiveUrl.trim()}
				class="inline-flex items-center gap-2 border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
			>
				{#if hiveConnecting}
					<Spinner size={14} />
					Opening Hive…
				{:else}
					<ExternalLink size={14} />
					Continue on Hive
				{/if}
			</button>
			<button
				type="button"
				onclick={onSkip}
				disabled={hiveConnecting}
				class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-ink transition-colors disabled:cursor-not-allowed disabled:opacity-60"
			>
				Skip for now
			</button>
		</div>
	{/if}

	{#if hiveError}
		<div
			class="border border-danger/40 bg-danger-soft px-3 py-2 text-sm leading-relaxed text-ink"
		>
			<div
				class="mb-1 text-xs font-semibold text-danger-ink"
			>
				Hive connection failed
			</div>
			{hiveError}
		</div>
	{:else if hiveStatus}
		<div
			class="border border-success/40 bg-success-soft px-3 py-2 text-sm leading-relaxed text-ink"
		>
			{hiveStatus}
		</div>
	{/if}
</div>

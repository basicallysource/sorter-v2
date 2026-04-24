<script lang="ts">
	import { Check, ExternalLink, Loader2 } from 'lucide-svelte';

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
		<div class="setup-panel flex items-center gap-2 px-4 py-3 text-sm text-text-muted">
			<Loader2 size={14} class="animate-spin" />
			Checking current Hive configuration…
		</div>
	{:else if officialHiveTarget}
		<div
			class="border border-success/40 bg-success/[0.06] px-4 py-3 dark:border-emerald-500/40 dark:bg-emerald-500/[0.08]"
		>
			<div class="flex items-start gap-3">
				<div
					class="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-success text-white"
				>
					<Check size={14} strokeWidth={3} />
				</div>
				<div class="flex min-w-0 flex-1 flex-col gap-1">
					<div
						class="text-xs font-semibold tracking-wider text-success-dark uppercase dark:text-emerald-200"
					>
						Connected to Hive
					</div>
					<div class="text-sm leading-relaxed text-text">
						This sorter is registered with
						<span class="font-mono">{officialHiveTarget.url}</span>.
					</div>
					{#if officialHiveTarget.machine_id}
						<div class="text-xs text-text-muted">
							Machine ID
							<span class="font-mono text-text">{officialHiveTarget.machine_id}</span>
						</div>
					{/if}
				</div>
			</div>
		</div>
		<div class="text-xs text-text-muted">
			You can manage this connection later under Settings › Hive. Click Continue to finish the
			setup wizard.
		</div>
	{:else}
		<div class="setup-panel flex flex-col gap-2 px-4 py-3">
			<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
				Hive server
			</div>
			<input
				type="url"
				bind:value={hiveUrl}
				placeholder={defaultHiveUrl}
				class="setup-control px-3 py-2 font-mono text-sm text-text"
				disabled={hiveConnecting}
			/>
			<div class="text-xs text-text-muted">
				Uses the official community platform by default. You can enter a local or custom Hive
				URL here for development.
			</div>
		</div>

		<div class="setup-panel flex flex-col gap-1 px-4 py-3">
			<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
				Machine name
			</div>
			<div class="text-sm text-text">{machineDisplayName}</div>
			<div class="text-xs text-text-muted">
				This is how your sorter will appear in Hive. Change it in Step 1 if needed.
			</div>
		</div>

		<div class="flex flex-wrap items-center gap-2">
			<button
				type="button"
				onclick={onConnect}
				disabled={hiveConnecting || !hiveUrl.trim()}
				class="inline-flex items-center gap-2 border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
			>
				{#if hiveConnecting}
					<Loader2 size={14} class="animate-spin" />
					Weiterleiten…
				{:else}
					<ExternalLink size={14} />
					In Hive fortfahren
				{/if}
			</button>
			<button
				type="button"
				onclick={onSkip}
				disabled={hiveConnecting}
				class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
			>
				Skip for now
			</button>
		</div>
	{/if}

	{#if hiveError}
		<div
			class="border border-danger/40 bg-danger/[0.06] px-3 py-2 text-sm leading-relaxed text-text dark:border-rose-500/40 dark:bg-rose-500/[0.08]"
		>
			<div
				class="mb-1 text-xs font-semibold tracking-wider text-danger-dark uppercase dark:text-rose-200"
			>
				Hive connection failed
			</div>
			{hiveError}
		</div>
	{:else if hiveStatus}
		<div
			class="border border-success/40 bg-success/[0.06] px-3 py-2 text-sm leading-relaxed text-text dark:border-emerald-500/40 dark:bg-emerald-500/[0.08]"
		>
			{hiveStatus}
		</div>
	{/if}
</div>

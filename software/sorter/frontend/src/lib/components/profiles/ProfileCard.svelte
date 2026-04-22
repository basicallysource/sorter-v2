<script lang="ts">
	import { Ellipsis } from 'lucide-svelte';
	import {
		displayVersion,
		sourceLabel,
		targetWebUrl,
		visibleVersions
	} from '$lib/sorting-profiles/api';
	import { formatAbsoluteTime, formatRelativeTime } from '$lib/sorting-profiles/format';
	import type {
		HiveTargetLibrary,
		SortingProfileDetail,
		SortingProfileRuleSummary,
		SortingProfileSummary,
		SortingProfileSyncState
	} from '$lib/sorting-profiles/types';

	type Props = {
		target: HiveTargetLibrary;
		profile: SortingProfileSummary;
		detail: SortingProfileDetail | undefined;
		detailError: string | undefined;
		syncState: SortingProfileSyncState | null;
		selectedVersionId: string | null;
		applyingKey: string | null;
		cardKey: string;
		openVersionMenuKey: string | null;
		onOpenDetails: () => void;
		onApply: () => void;
		onApplyVersion: (versionId: string) => void;
		onToggleVersionMenu: () => void;
	};

	const props: Props = $props();

	const isActive = $derived(props.syncState?.profile_id === props.profile.id);

	const isSelectedActive = $derived(
		isActive &&
			Boolean(props.selectedVersionId) &&
			props.syncState?.version_id === props.selectedVersionId
	);

	const update = $derived.by(() => {
		if (!props.syncState?.profile_id) return null;
		if (props.profile.id !== props.syncState.profile_id) return null;
		const currentVersion = props.syncState.version_number ?? 0;
		const latestPublished = props.profile.latest_published_version ?? props.profile.latest_version;
		if (!latestPublished) return null;
		if (latestPublished.version_number > currentVersion) {
			return { latest: latestPublished.version_number, current: currentVersion };
		}
		return null;
	});

	const rules: SortingProfileRuleSummary[] = $derived(
		(displayVersion(props.profile)?.rules_summary ?? []).filter((rule) => !rule.disabled)
	);

	const lastUsed = $derived.by(() => {
		if (props.syncState?.profile_id === props.profile.id) {
			return props.syncState.activated_at ?? props.syncState.applied_at ?? null;
		}
		const assignment = props.target.assignment;
		if (assignment?.profile?.id === props.profile.id) {
			return assignment.last_activated_at ?? assignment.last_synced_at ?? null;
		}
		return null;
	});

	const titleClass = $derived(
		isActive
			? 'text-primary'
			: props.profile.visibility === 'public'
				? 'text-primary dark:text-blue-400'
				: 'text-text'
	);
</script>

<div
	class="setup-card-shell group flex h-full flex-col overflow-hidden border transition-colors {isActive
		? 'border-success ring-1 ring-success/20'
		: 'border-border hover:border-text-muted'}"
>
	<div class="setup-card-header px-3 py-2 text-sm">
		<div class="flex items-center justify-between gap-3">
			<div class="min-w-0 flex-1">
				<button
					type="button"
					onclick={props.onOpenDetails}
					class="flex max-w-full items-center gap-2 truncate text-left text-sm font-semibold {titleClass} hover:underline"
				>
					{props.profile.name}
				</button>
				{#if isActive}
					<div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-muted">
						<span
							class="border border-success/30 bg-success/10 px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-success"
							>Active</span
						>
					</div>
				{/if}
				{#if update}
					<div class="mt-1 text-xs text-amber-600">
						v{update.latest} available (you're on v{update.current})
					</div>
				{/if}
			</div>
			<div class="flex shrink-0 items-center gap-2 self-center">
				{#if props.detailError}
					<div
						class="min-w-[10.5rem] border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300"
					>
						Unavailable
					</div>
				{:else if props.detail}
					<div class="relative flex items-stretch">
						<button
							onclick={(event) => {
								event.stopPropagation();
								props.onApply();
							}}
							disabled={props.applyingKey === props.cardKey}
							class="border border-border bg-white px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:opacity-50"
						>
							{props.applyingKey === props.cardKey ? 'Activating...' : 'activate'}
						</button>
						<button
							type="button"
							onclick={(event) => {
								event.stopPropagation();
								props.onToggleVersionMenu();
							}}
							disabled={props.applyingKey === props.cardKey}
							class="border border-l-0 border-border bg-white px-2 py-2 text-text transition-colors hover:bg-bg disabled:opacity-50"
							title="Choose version"
						>
							<Ellipsis size={16} />
						</button>
						{#if props.openVersionMenuKey === props.cardKey}
							<div
								class="absolute top-full right-0 z-10 mt-1 min-w-[14rem] border border-border bg-surface shadow-lg"
							>
								{#each visibleVersions(props.detail) as version}
									<button
										type="button"
										onclick={(event) => {
											event.stopPropagation();
											props.onApplyVersion(version.id);
										}}
										class="flex w-full items-center justify-between gap-3 border-b border-border px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg last:border-b-0"
									>
										<span
											>v{version.version_number}{version.label
												? ` - ${version.label}`
												: ''}</span
										>
										{#if !version.is_published}
											<span class="text-xs text-text-muted">draft</span>
										{/if}
									</button>
								{/each}
							</div>
						{/if}
					</div>
				{:else}
					<div class="min-w-[10.5rem] border border-border bg-bg px-3 py-2 text-sm text-text opacity-60">
						Loading...
					</div>
				{/if}
			</div>
		</div>
	</div>

	{#if rules.length > 0}
		<div class="setup-card-body border-t border-border px-4 py-3">
			<div class="grid gap-x-4 gap-y-1.5 md:grid-cols-2">
				{#each rules.slice(0, 8) as rule}
					<div class="flex items-center gap-2 text-xs" title={rule.set_num ?? rule.name}>
						{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
							<img src={rule.set_meta.img_url} alt="" class="h-5 w-5 shrink-0 object-contain" />
						{:else}
							<svg class="h-3.5 w-3.5 shrink-0 text-text-muted" viewBox="0 0 20 20" fill="currentColor"
								><path
									fill-rule="evenodd"
									d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.092 1.092a4 4 0 00-5.558-5.558z"
									clip-rule="evenodd"
								/><path
									d="M10.748 13.93l2.523 2.523a9.987 9.987 0 01-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 010-1.186A10.007 10.007 0 012.839 6.02L6.07 9.252a4 4 0 004.678 4.678z"
								/></svg
							>
						{/if}
						<span class="truncate text-text">{rule.name}</span>
					</div>
				{/each}
				{#if rules.length > 8}
					<button
						type="button"
						onclick={props.onOpenDetails}
						class="text-xs text-text-muted hover:text-text hover:underline md:col-span-2"
						>+{rules.length - 8} more rules</button
					>
				{/if}
			</div>
		</div>
	{:else}
		<div class="setup-card-body border-t border-border px-4 py-3">
			<span class="text-xs text-text-muted">No rules defined</span>
		</div>
	{/if}

	<div class="setup-card-body border-t border-border px-4 py-3">
		<div class="grid items-center gap-3 text-xs text-text-muted md:grid-cols-[1fr_auto_1fr]">
			<div>
				{#if lastUsed}
					<span title={formatAbsoluteTime(lastUsed) ?? undefined} class="cursor-help">
						Last used {formatRelativeTime(lastUsed) ?? 'recently'}
					</span>
				{/if}
			</div>
			<div class="text-center">
				{#if targetWebUrl(props.target)}
					<a
						href={targetWebUrl(props.target) ?? undefined}
						target="_blank"
						rel="noreferrer"
						class="transition-colors hover:text-text hover:underline"
					>
						{sourceLabel(props.target)}
					</a>
				{:else}
					{sourceLabel(props.target)}
				{/if}
			</div>
			<div class="text-right">
				{#if displayVersion(props.profile)?.created_at}
					<span
						title={formatAbsoluteTime(displayVersion(props.profile)?.created_at) ?? undefined}
						class="cursor-help"
					>
						Updated {formatRelativeTime(displayVersion(props.profile)?.created_at) ?? 'recently'}
					</span>
				{/if}
			</div>
		</div>
		{#if props.detailError}
			<div class="mt-2 text-xs text-amber-700 dark:text-amber-300">
				Could not load versions: {props.detailError}
			</div>
		{/if}
		{#if isSelectedActive}
			<div class="mt-2 text-xs text-primary">Currently active on this machine.</div>
		{:else if isActive && props.syncState?.version_number}
			<div class="mt-2 text-sm text-text-muted">
				This profile is active on v{props.syncState.version_number}.
			</div>
		{/if}
	</div>
</div>

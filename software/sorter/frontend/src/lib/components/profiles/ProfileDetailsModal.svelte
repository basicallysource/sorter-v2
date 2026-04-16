<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import ProfileRuleTreeNode from '$lib/components/ProfileRuleTreeNode.svelte';
	import { visibleVersions } from '$lib/sorting-profiles/api';
	import { formatRelativeTime } from '$lib/sorting-profiles/format';
	import type { SortingProfileDetail } from '$lib/sorting-profiles/types';

	type Props = {
		open: boolean;
		summary: SortingProfileDetail | null;
		detail: SortingProfileDetail | null;
		loading: boolean;
		error: string | null;
		selectedVersionId: string | null;
		onVersionChange: (versionId: string) => void;
	};

	let {
		open = $bindable(),
		summary,
		detail,
		loading,
		error,
		selectedVersionId,
		onVersionChange
	}: Props = $props();

	const versionSelectId = 'profile-details-version-select';

	function categoryEntries(
		current: SortingProfileDetail | null
	): [string, Record<string, unknown>][] {
		if (!current?.current_version?.categories) return [];
		return Object.entries(current.current_version.categories);
	}
</script>

<Modal bind:open title="Profile Details" wide={true}>
	{#if !summary}
		<div class="py-6 text-sm text-text-muted">No profile details loaded.</div>
	{:else}
		<div class="space-y-5">
			<div
				class="flex flex-col gap-4 border border-border bg-surface p-4 lg:flex-row lg:items-start lg:justify-between"
			>
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-2">
						<h3 class="text-lg font-semibold text-text">{summary.name}</h3>
						{#if summary.profile_type === 'set'}
							<span
								class="border border-border bg-bg px-2 py-1 text-xs font-medium text-text-muted"
							>
								Set profile
							</span>
						{/if}
						{#if summary.visibility}
							<span
								class="border border-border bg-bg px-2 py-1 text-xs font-medium text-text-muted"
							>
								{summary.visibility}
							</span>
						{/if}
					</div>
					{#if summary.description}
						<p class="mt-2 text-sm text-text-muted">{summary.description}</p>
					{/if}
					<div class="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-text-muted">
						<span>
							Owner:
							{summary.owner?.display_name ?? summary.owner?.github_login ?? 'Unknown'}
						</span>
						{#if summary.tags.length > 0}
							<span>Tags: {summary.tags.join(', ')}</span>
						{/if}
						{#if detail?.current_version?.default_category_id}
							<span>Default category: {detail.current_version.default_category_id}</span>
						{/if}
					</div>
				</div>
				<div class="w-full max-w-sm space-y-2">
					<label
						for={versionSelectId}
						class="block text-xs font-semibold uppercase tracking-wide text-text-muted"
					>
						Version
					</label>
					<select
						id={versionSelectId}
						value={selectedVersionId ?? ''}
						onchange={(event) =>
							onVersionChange((event.currentTarget as HTMLSelectElement).value)}
						class="w-full border border-border bg-bg px-3 py-2 text-sm text-text focus:border-text-muted focus:outline-none"
					>
						{#each visibleVersions(summary) as version}
							<option value={version.id}>
								v{version.version_number}
								{version.label ? ` - ${version.label}` : ''}
								{version.is_published ? '' : ' (draft)'}
							</option>
						{/each}
					</select>
					{#if detail?.current_version}
						<div class="text-xs text-text-muted">
							{#if detail.current_version.change_note}
								<div>Change note: {detail.current_version.change_note}</div>
							{/if}
							<div>
								Updated {formatRelativeTime(detail.current_version.created_at) ?? 'recently'}
							</div>
						</div>
					{/if}
				</div>
			</div>

			{#if error}
				<div
					class="border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300"
				>
					{error}
				</div>
			{/if}

			{#if loading && !detail}
				<div class="py-8 text-center text-sm text-text-muted">
					Loading full profile details...
				</div>
			{:else if detail?.current_version}
				<div class="grid gap-4 lg:grid-cols-[minmax(0,2fr),minmax(18rem,1fr)]">
					<div class="space-y-4">
						<div class="border border-border bg-surface p-4">
							<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
								Rule Tree
							</div>
							{#if detail.current_version.rules.length > 0}
								<div class="space-y-3">
									{#each detail.current_version.rules as rule (rule.id)}
										<ProfileRuleTreeNode rule={rule} />
									{/each}
								</div>
							{:else}
								<div class="text-sm text-text-muted">This version has no rules.</div>
							{/if}
						</div>
					</div>

					<div class="space-y-4">
						<div class="border border-border bg-surface p-4">
							<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
								Compiled Stats
							</div>
							<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
								<div class="border border-border bg-bg px-3 py-2">
									<div class="text-[11px] uppercase tracking-wide text-text-muted">Matched</div>
									<div class="text-lg font-semibold text-text">
										{(detail.current_version.compiled_stats?.matched ?? 0).toLocaleString()}
									</div>
								</div>
								<div class="border border-border bg-bg px-3 py-2">
									<div class="text-[11px] uppercase tracking-wide text-text-muted">Total parts</div>
									<div class="text-lg font-semibold text-text">
										{(detail.current_version.compiled_stats?.total_parts ?? 0).toLocaleString()}
									</div>
								</div>
								<div class="border border-border bg-bg px-3 py-2">
									<div class="text-[11px] uppercase tracking-wide text-text-muted">Unmatched</div>
									<div class="text-lg font-semibold text-text">
										{(detail.current_version.compiled_stats?.unmatched ?? 0).toLocaleString()}
									</div>
								</div>
								<div class="border border-border bg-bg px-3 py-2">
									<div class="text-[11px] uppercase tracking-wide text-text-muted">Categories</div>
									<div class="text-lg font-semibold text-text">
										{categoryEntries(detail).length.toLocaleString()}
									</div>
								</div>
							</div>
						</div>

						<div class="border border-border bg-surface p-4">
							<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
								Fallback
							</div>
							<div class="flex flex-wrap gap-2">
								<span class="border border-border bg-bg px-2 py-1 text-xs text-text-muted">
									Rebrickable: {detail.current_version.fallback_mode?.rebrickable_categories
										? 'On'
										: 'Off'}
								</span>
								<span class="border border-border bg-bg px-2 py-1 text-xs text-text-muted">
									BrickLink: {detail.current_version.fallback_mode?.bricklink_categories
										? 'On'
										: 'Off'}
								</span>
								<span class="border border-border bg-bg px-2 py-1 text-xs text-text-muted">
									By color: {detail.current_version.fallback_mode?.by_color ? 'On' : 'Off'}
								</span>
							</div>
						</div>

						<div class="border border-border bg-surface p-4">
							<div class="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
								Categories
							</div>
							{#if categoryEntries(detail).length > 0}
								<div class="max-h-[24rem] space-y-2 overflow-y-auto">
									{#each categoryEntries(detail) as [categoryId, category]}
										<div class="border border-border bg-bg px-3 py-2">
											<div class="text-sm font-medium text-text">
												{String(category.name ?? categoryId)}
											</div>
											<div class="mt-1 text-xs text-text-muted">
												<span class="font-mono">{categoryId}</span>
												{#if category.set_num}
													<span class="mx-1">&middot;</span>
													<span>{String(category.set_num)}</span>
												{/if}
												{#if category.year != null}
													<span class="mx-1">&middot;</span>
													<span>{String(category.year)}</span>
												{/if}
											</div>
										</div>
									{/each}
								</div>
							{:else}
								<div class="text-sm text-text-muted">No category metadata available.</div>
							{/if}
						</div>
					</div>
				</div>
			{:else}
				<div class="text-sm text-text-muted">No version details available for this profile.</div>
			{/if}
		</div>
	{/if}
</Modal>

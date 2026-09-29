<script lang="ts">
	import ProfileRuleTreeNode from '$lib/components/ProfileRuleTreeNode.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
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

<Modal bind:open title="Profile details" size="lg">
	{#if !summary}
		<EmptyState title="No profile details are loaded" />
	{:else}
		<div class="flex flex-col gap-6">
			<div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-2">
						<h3 class="text-base font-semibold text-ink">{summary.name}</h3>
						{#if summary.profile_type === 'set'}<Badge>Set profile</Badge>{/if}
						{#if summary.visibility}<Badge>{summary.visibility}</Badge>{/if}
					</div>
					{#if summary.description}
						<p class="mt-2 text-ink-muted">{summary.description}</p>
					{/if}
					<p class="mt-2 text-ink-muted">
						Owner: {summary.owner?.display_name ?? summary.owner?.github_login ?? 'Unknown'}
						{#if summary.tags.length > 0}<br />Tags: {summary.tags.join(', ')}{/if}
						{#if detail?.current_version?.default_category_id}
							<br />Default category: {detail.current_version.default_category_id}
						{/if}
					</p>
				</div>
				<div class="w-full shrink-0 sm:w-64">
					<Field
						label="Version"
						for={versionSelectId}
						help={detail?.current_version
							? `${detail.current_version.change_note ? `${detail.current_version.change_note.replace(/[.!?]+$/, '')}. ` : ''}Updated ${formatRelativeTime(detail.current_version.created_at) ?? 'recently'}.`
							: undefined}
					>
						<Select
							id={versionSelectId}
							value={selectedVersionId ?? ''}
							options={visibleVersions(summary).map((version) => ({
								value: version.id,
								label: `v${version.version_number}${version.label ? ` - ${version.label}` : ''}${version.is_published ? '' : ' (draft)'}`
							}))}
							onchange={onVersionChange}
						/>
					</Field>
				</div>
			</div>

			{#if error}<Alert tone="warning">{error}</Alert>{/if}

			{#if loading && !detail}
				<p class="flex items-center justify-center gap-2 py-8 text-ink-muted">
					<Spinner size={16} />
					Loading the full profile details
				</p>
			{:else if detail?.current_version}
				{@const version = detail.current_version}
				<div class="grid grid-cols-2 gap-px overflow-hidden rounded-control bg-line sm:grid-cols-4">
					{#each [['Matched', version.compiled_stats?.matched], ['Total parts', version.compiled_stats?.total_parts], ['Unmatched', version.compiled_stats?.unmatched], ['Categories', categoryEntries(detail).length]] as [label, value] (label)}
						<div class="bg-well p-3">
							<Stat label={String(label)} value={Number(value ?? 0).toLocaleString()} />
						</div>
					{/each}
				</div>

				<section>
					<h3 class="mb-2 text-base font-semibold text-ink">Fallback</h3>
					<div class="flex flex-wrap gap-2">
						<Badge>Rebrickable: {version.fallback_mode?.rebrickable_categories ? 'On' : 'Off'}</Badge>
						<Badge>BrickLink: {version.fallback_mode?.bricklink_categories ? 'On' : 'Off'}</Badge>
						<Badge>By color: {version.fallback_mode?.by_color ? 'On' : 'Off'}</Badge>
					</div>
				</section>

				<section>
					<h3 class="mb-2 text-base font-semibold text-ink">Rule tree</h3>
					{#if version.rules.length > 0}
						<div class="flex flex-col gap-5">
							{#each version.rules as rule (rule.id)}
								<ProfileRuleTreeNode {rule} />
							{/each}
						</div>
					{:else}
						<p class="text-ink-muted">This version has no rules.</p>
					{/if}
				</section>

				<section>
					<h3 class="mb-2 text-base font-semibold text-ink">Categories</h3>
					{#if categoryEntries(detail).length > 0}
						<ul class="max-h-96 divide-y divide-line overflow-y-auto">
							{#each categoryEntries(detail) as [categoryId, category]}
								<li class="py-2">
									<div class="font-medium text-ink">{String(category.name ?? categoryId)}</div>
									<div class="mt-0.5 text-ink-muted">
										<span class="font-mono">{categoryId}</span>
										{#if category.set_num}<span class="mx-1">&middot;</span>{String(category.set_num)}{/if}
										{#if category.year != null}<span class="mx-1">&middot;</span>{String(category.year)}{/if}
									</div>
								</li>
							{/each}
						</ul>
					{:else}
						<p class="text-ink-muted">No category metadata is available.</p>
					{/if}
				</section>
			{:else}
				<p class="text-ink-muted">No version details are available for this profile.</p>
			{/if}
		</div>
	{/if}
</Modal>

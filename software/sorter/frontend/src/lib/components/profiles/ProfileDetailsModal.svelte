<script lang="ts">
	import ProfileBinsView from '$lib/components/profiles/ProfileBinsView.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { visibleVersions } from '$lib/sorting-profiles/api';
	import { savedBy } from '$lib/sorting-profiles/bins';
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

	// "Changed the colors. Updated 3 minutes ago by the assistant."
	const versionHelp = $derived.by(() => {
		const version = detail?.current_version;
		if (!version) return undefined;
		const note = version.change_note ? `${version.change_note.replace(/[.!?]+$/, '')}. ` : '';
		const by = savedBy(version);
		return `${note}Updated ${formatRelativeTime(version.created_at) ?? 'recently'}${by ? ` ${by}` : ''}.`;
	});
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
						{#if summary.is_default}<Badge>Hive default</Badge>{/if}
						{#if summary.profile_type === 'set'}<Badge>Set profile</Badge>{/if}
						{#if summary.visibility && !summary.is_default}<Badge>{summary.visibility}</Badge>{/if}
					</div>
					{#if summary.description}
						<p class="mt-2 text-ink-muted">{summary.description}</p>
					{/if}
					{#if !summary.is_default || summary.tags.length > 0}
						<p class="mt-2 text-ink-muted">
							{#if !summary.is_default}
								Owner: {summary.owner?.display_name ?? summary.owner?.github_login ?? 'Unknown'}
							{/if}
							{#if !summary.is_default && summary.tags.length > 0}<br />{/if}
							{#if summary.tags.length > 0}Tags: {summary.tags.join(', ')}{/if}
						</p>
					{/if}
				</div>
				<div class="w-full shrink-0 sm:w-64">
					<Field label="Version" for={versionSelectId} help={versionHelp}>
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
					Loading the bins
				</p>
			{:else if detail?.current_version}
				{@const version = detail.current_version}
				<ProfileBinsView
					categories={version.categories ?? {}}
					order={version.category_order}
					warnings={version.warnings}
					fallback={version.fallback_mode}
					stats={version.compiled_stats}
				/>
			{:else}
				<p class="text-ink-muted">No version details are available for this profile.</p>
			{/if}
		</div>
	{/if}
</Modal>

<script lang="ts">
	// The profile this machine sorts with now: which one and which version, what
	// it sorts into, and a notice when Hive has a newer version of it.
	import Boxes from '@lucide/svelte/icons/boxes';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { formatRelativeTime } from '$lib/sorting-profiles/format';
	import type { LocalProfileStatus, SortingProfileSyncState } from '$lib/sorting-profiles/types';
	import type { SortingProfileMetadata } from '$lib/stores/sortingProfile.svelte';

	type Props = {
		syncState: SortingProfileSyncState | null;
		localProfile: LocalProfileStatus | null;
		metadata: SortingProfileMetadata | null;
		// A newer version of this profile on Hive than the machine runs.
		update: { latest: number; current: number } | null;
		updating: boolean;
		onUpdate: () => void;
		onOpenBins: () => void;
	};

	let { syncState, localProfile, metadata, update, updating, onUpdate, onOpenBins }: Props =
		$props();

	const name = $derived(syncState?.profile_name ?? localProfile?.name ?? metadata?.name ?? null);
	const from = $derived.by(() => {
		if (syncState?.source === 'local') {
			return `Saved on this machine as ${syncState.local_filename ?? 'a file'}`;
		}
		const target = syncState?.target_name;
		if (!target) return null;
		return /hive/i.test(target) ? `From ${target}` : `From Hive, ${target}`;
	});
	const applied = $derived(
		formatRelativeTime(syncState?.applied_at ?? localProfile?.updated_at ?? null)
	);
	// What it sorts into, in a sentence: "50 categories; 59,000 of 81,000 known parts are sorted."
	const sorts = $derived.by(() => {
		if (!metadata) return null;
		const count = Object.keys(metadata.categories ?? {}).length;
		const bins = `${whole(count)} ${count === 1 ? 'category' : 'categories'}`;
		const { sorted, total_parts: total } = metadata.stats ?? {};
		if (sorted == null || total == null) return `${bins}.`;
		return sorted === total
			? `${bins}; all ${whole(total)} known parts are sorted.`
			: `${bins}; ${whole(sorted)} of ${whole(total)} known parts are sorted, the rest go to Everything else.`;
	});

	function whole(n: number) {
		return n.toLocaleString('en-US');
	}
</script>

<Panel title="On this machine" description="The profile this machine sorts with now.">
	{#snippet actions()}
		<Button size="sm" icon={Boxes} onclick={onOpenBins}>See its categories</Button>
	{/snippet}
	<div class="flex flex-col gap-3">
		<div>
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
				<span class="text-base font-semibold text-ink">{name ?? 'A profile with no name'}</span>
				{#if syncState?.version_number}
					<Badge
						>v{syncState.version_number}{syncState.version_label
							? ` · ${syncState.version_label}`
							: ''}</Badge
					>
				{/if}
			</div>
			<p class="mt-0.5 text-sm text-ink-muted">
				{[from, applied && `applied ${applied}`].filter(Boolean).join(', ')}
			</p>
			{#if sorts}<p class="mt-0.5 text-sm text-ink-muted">{sorts}</p>{/if}
		</div>

		{#if update}
			<Alert tone="info" title="v{update.latest} is on Hive; this machine runs v{update.current}">
				The bins keep what is in them.
				{#snippet actions()}
					<Button variant="primary" size="sm" loading={updating} onclick={onUpdate}>Update</Button>
				{/snippet}
			</Alert>
		{/if}
	</div>
</Panel>

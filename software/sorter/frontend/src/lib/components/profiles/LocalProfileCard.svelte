<script lang="ts">
	import Boxes from '@lucide/svelte/icons/boxes';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import type { LocalSortingProfile } from '$lib/sorting-profiles/types';

	let {
		profile,
		activating,
		deleting,
		onActivate,
		onDelete,
		onOpenBins
	}: {
		profile: LocalSortingProfile;
		activating: boolean;
		deleting: boolean;
		onActivate: () => void;
		onDelete: () => void;
		// The profile the machine runs can show its bins.
		onOpenBins?: () => void;
	} = $props();

	const summary = $derived(
		[
			`${profile.rule_count} ${profile.rule_count === 1 ? 'rule' : 'rules'}`,
			profile.category_count != null
				? `${profile.category_count} ${profile.category_count === 1 ? 'category' : 'categories'}`
				: null
		]
			.filter(Boolean)
			.join(' · ')
	);
</script>

<!-- A profile saved on this machine: not something to open, so a panel, not a Card. -->
<Panel class="h-full">
	<div class="flex h-full flex-col gap-3">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0 flex-1">
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
					<h3 class="truncate text-base font-semibold text-ink">
						{profile.name || profile.filename}
					</h3>
					{#if profile.is_active}<Badge tone="success" dot>Active</Badge>{/if}
				</div>
				<p class="mt-0.5 truncate font-mono text-xs text-ink-muted">local:{profile.filename}</p>
			</div>
			<div class="flex shrink-0 items-center gap-1">
				<Button
					size="sm"
					loading={activating}
					disabled={Boolean(profile.error)}
					onclick={onActivate}
				>
					Activate
				</Button>
				<Button
					size="sm"
					variant="ghost"
					icon={Trash2}
					label="Delete this local profile"
					disabled={deleting}
					onclick={onDelete}
				/>
			</div>
		</div>
		{#if profile.error}
			<p class="text-sm text-warning-ink">Unreadable: {profile.error}</p>
		{:else if profile.rule_count == null}
			<Skeleton class="h-4 w-32" />
		{:else}
			<div class="flex flex-wrap items-center justify-between gap-2">
				<p class="text-sm text-ink-muted">{summary}</p>
				{#if profile.is_active && onOpenBins}
					<Button size="sm" variant="ghost" icon={Boxes} onclick={onOpenBins}>See its categories</Button>
				{/if}
			</div>
		{/if}
	</div>
</Panel>

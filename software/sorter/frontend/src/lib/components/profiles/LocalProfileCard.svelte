<script lang="ts">
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import type { LocalSortingProfile } from '$lib/sorting-profiles/types';

	let {
		profile,
		activating,
		deleting,
		onActivate,
		onDelete,
		onOpen
	}: {
		profile: LocalSortingProfile;
		activating: boolean;
		deleting: boolean;
		onActivate: () => void;
		onDelete: () => void;
		// Shows what the profile sorts into and its description.
		onOpen: () => void;
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

<Card label={profile.name || profile.filename} onclick={onOpen} class="h-full">
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
				{#if profile.description}
					<p class="mt-2 line-clamp-2 text-sm text-ink-muted">{profile.description}</p>
				{/if}
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
			<p class="text-sm text-ink-muted">{summary}</p>
		{/if}
	</div>
</Card>

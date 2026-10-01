<script lang="ts">
	// The bins of the profile this machine runs, from the machine itself: the
	// same view as a version on Hive, for a profile that may never have been on
	// Hive (a file saved here).
	import ProfileBinsView from '$lib/components/profiles/ProfileBinsView.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import type { SortingProfileMetadata } from '$lib/stores/sortingProfile.svelte';

	type Props = {
		open: boolean;
		metadata: SortingProfileMetadata | null;
		loading: boolean;
		error: string | null;
	};

	let { open = $bindable(), metadata, loading, error }: Props = $props();
</script>

<Modal bind:open title="What this machine sorts into" size="lg">
	<div class="flex flex-col gap-6">
		{#if metadata}
			<div>
				<h3 class="text-base font-semibold text-ink">{metadata.name}</h3>
				{#if metadata.description}<p class="mt-1 text-ink-muted">{metadata.description}</p>{/if}
			</div>
		{/if}

		{#if error}<Alert tone="warning">{error}</Alert>{/if}

		{#if loading && !metadata}
			<p class="flex items-center justify-center gap-2 py-8 text-ink-muted">
				<Spinner size={16} />
				Loading the bins
			</p>
		{:else if metadata}
			<ProfileBinsView
				categories={metadata.categories ?? {}}
				order={metadata.category_order}
				fallback={metadata.fallback_mode}
				stats={metadata.stats}
			/>
		{:else if !error}
			<p class="text-ink-muted">This machine has no profile to show.</p>
		{/if}
	</div>
</Modal>

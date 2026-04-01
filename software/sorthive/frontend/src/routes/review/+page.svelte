<script lang="ts">
	import { api, type Sample } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let sample = $state<Sample | null>(null);
	let loading = $state(true);
	let submitting = $state(false);
	let notes = $state('');
	let lastResult = $state<{ decision: string; status: string } | null>(null);
	let empty = $state(false);
	let error = $state<string | null>(null);

	$effect(() => {
		loadNext();
	});

	async function loadNext() {
		loading = true;
		lastResult = null;
		notes = '';
		error = null;
		try {
			const result = await api.getNextReview();
			if (result && result.id) {
				sample = result;
				empty = false;
			} else {
				sample = null;
				empty = true;
			}
		} catch {
			sample = null;
			empty = true;
		} finally {
			loading = false;
		}
	}

	async function submitReview(decision: 'accept' | 'reject') {
		if (!sample) return;
		submitting = true;
		error = null;
		try {
			const review = await api.submitReview(sample.id, decision, notes || undefined);
			lastResult = { decision: review.decision, status: 'submitted' };
			// Auto-load next after brief pause
			setTimeout(() => loadNext(), 1000);
		} catch (e) {
			error = (e as { error?: string }).error || 'Failed to submit review';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Review - SortHive</title>
</svelte:head>

<h1 class="mb-6 text-2xl font-bold text-gray-900">Review Queue</h1>

{#if loading}
	<Spinner />
{:else if empty}
	<div class="rounded-lg border border-gray-200 bg-white p-8 text-center">
		<p class="text-lg text-gray-500">No more samples to review.</p>
		<p class="mt-2 text-sm text-gray-400">Check back later for new samples.</p>
	</div>
{:else if sample}
	{#if lastResult}
		<div class="mb-4 rounded-lg bg-green-50 p-3 text-sm text-green-700">
			Review submitted: <strong>{lastResult.decision}</strong>. Loading next sample...
		</div>
	{/if}

	{#if error}
		<div class="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
	{/if}

	<div class="grid gap-6 lg:grid-cols-3">
		<div class="lg:col-span-2">
			<div class="overflow-hidden rounded-lg border border-gray-200 bg-white">
				<img
					src={api.sampleImageUrl(sample.id)}
					alt="Sample to review"
					class="w-full"
				/>
			</div>
		</div>

		<div class="space-y-4">
			<div class="rounded-lg border border-gray-200 bg-white p-4">
				<div class="mb-3 flex items-center gap-2">
					<Badge text={sample.review_status} variant="info" />
					{#if sample.source_role}
						<Badge text={sample.source_role} variant="neutral" />
					{/if}
				</div>
				<p class="text-xs text-gray-500">Sample #{sample.id}</p>
				{#if sample.detection_algorithm}
					<p class="mt-1 text-xs text-gray-500">
						Detection: {sample.detection_algorithm} (count: {sample.detection_count})
					</p>
				{/if}
			</div>

			<div>
				<label for="notes" class="mb-1 block text-sm font-medium text-gray-700">Notes (optional)</label>
				<textarea
					id="notes"
					bind:value={notes}
					rows="3"
					class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
					placeholder="Add notes about this sample..."
				></textarea>
			</div>

			<div class="flex gap-3">
				<button
					onclick={() => submitReview('accept')}
					disabled={submitting}
					class="flex-1 rounded-lg bg-green-600 px-4 py-3 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
				>
					Accept
				</button>
				<button
					onclick={() => submitReview('reject')}
					disabled={submitting}
					class="flex-1 rounded-lg bg-red-600 px-4 py-3 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
				>
					Reject
				</button>
			</div>

			<button
				onclick={loadNext}
				disabled={submitting}
				class="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
			>
				Skip
			</button>
		</div>
	</div>
{/if}

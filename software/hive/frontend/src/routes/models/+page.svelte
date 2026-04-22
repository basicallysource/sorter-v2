<script lang="ts">
	import { api, type PaginatedDetectionModels } from '$lib/api';
	import ModelCard from '$lib/components/ModelCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let data = $state<PaginatedDetectionModels | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let filterScope = $state<string>('');
	let filterRuntime = $state<string>('');
	let filterFamily = $state<string>('');
	let query = $state<string>('');
	let currentPage = $state(1);
	const pageSize = 30;

	const scopeOptions = [
		'',
		'classification_chamber',
		'c_channel',
		'carousel',
		'top_camera',
		'bottom_camera'
	];
	const runtimeOptions = ['', 'onnx', 'ncnn', 'hailo', 'pytorch'];

	$effect(() => {
		void filterScope;
		void filterRuntime;
		void filterFamily;
		void query;
		void currentPage;
		void load();
	});

	async function load() {
		loading = true;
		error = null;
		try {
			data = await api.getModels({
				page: currentPage,
				page_size: pageSize,
				scope: filterScope || undefined,
				runtime: filterRuntime || undefined,
				family: filterFamily || undefined,
				q: query || undefined
			});
		} catch (err: unknown) {
			const apiErr = err as { error?: string };
			error = apiErr?.error || 'Failed to load models';
		} finally {
			loading = false;
		}
	}

	function clearFilters() {
		filterScope = '';
		filterRuntime = '';
		filterFamily = '';
		query = '';
		currentPage = 1;
	}
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-2xl font-bold text-[var(--color-text)]">Detection Models</h1>
		<p class="text-sm text-[var(--color-text-muted)]">Published model catalog — browse and download model variants.</p>
	</div>

	<div class="flex flex-wrap items-end gap-3 border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
		<label class="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
			<span>Search</span>
			<input
				type="text"
				bind:value={query}
				placeholder="slug or name"
				class="border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-sm text-[var(--color-text)]"
			/>
		</label>
		<label class="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
			<span>Scope</span>
			<select
				bind:value={filterScope}
				class="border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-sm text-[var(--color-text)]"
			>
				{#each scopeOptions as opt (opt)}
					<option value={opt}>{opt || 'Any scope'}</option>
				{/each}
			</select>
		</label>
		<label class="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
			<span>Runtime</span>
			<select
				bind:value={filterRuntime}
				class="border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-sm text-[var(--color-text)]"
			>
				{#each runtimeOptions as opt (opt)}
					<option value={opt}>{opt || 'Any runtime'}</option>
				{/each}
			</select>
		</label>
		<label class="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
			<span>Family</span>
			<input
				type="text"
				bind:value={filterFamily}
				placeholder="yolo, nanodet, …"
				class="border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-sm text-[var(--color-text)]"
			/>
		</label>
		<button
			onclick={clearFilters}
			class="border border-[var(--color-border)] px-3 py-1 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
			type="button"
		>
			Reset
		</button>
	</div>

	{#if error}
		<div class="border border-primary bg-primary-light p-3 text-sm text-primary">{error}</div>
	{/if}

	{#if loading && !data}
		<div class="flex justify-center py-12"><Spinner /></div>
	{:else if data && data.items.length === 0}
		<div class="border border-dashed border-[var(--color-border)] p-8 text-center text-sm text-[var(--color-text-muted)]">
			No models match the current filters.
		</div>
	{:else if data}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
			{#each data.items as model (model.id)}
				<ModelCard {model} />
			{/each}
		</div>

		{#if data.pages > 1}
			<div class="flex items-center justify-center gap-2">
				<button
					disabled={currentPage <= 1}
					onclick={() => { currentPage = Math.max(1, currentPage - 1); }}
					class="border border-[var(--color-border)] px-3 py-1 text-sm disabled:opacity-40"
					type="button"
				>
					Prev
				</button>
				<span class="text-sm text-[var(--color-text-muted)]">
					Page {data.page} / {data.pages} · {data.total} total
				</span>
				<button
					disabled={currentPage >= data.pages}
					onclick={() => { const total = data?.pages ?? 1; currentPage = Math.min(total, currentPage + 1); }}
					class="border border-[var(--color-border)] px-3 py-1 text-sm disabled:opacity-40"
					type="button"
				>
					Next
				</button>
			</div>
		{/if}
	{/if}
</div>

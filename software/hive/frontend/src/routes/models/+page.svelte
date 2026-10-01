<script lang="ts">
	import { api, type PaginatedDetectionModels } from '$lib/api';
	import ModelCard from '$lib/components/ModelCard.svelte';
	import { sentence } from '$lib/text';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';
	import Boxes from '@lucide/svelte/icons/boxes';

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
				q: query || undefined,
				// Show experimental models in the web catalog — they are flagged with a
				// badge rather than hidden. (The sorter's /api/machine/models still
				// hides them by default so operators don't install one by accident.)
				include_experimental: true
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

<svelte:head>
	<title>Models - Hive</title>
</svelte:head>

<PageHeader title="Detection models" description="The published models, with a download for each runtime." />

<div class="flex flex-wrap items-end gap-3">
	<Field label="Search" for="model-search" class="w-full sm:w-56">
		<Input id="model-search" type="search" bind:value={query} placeholder="Slug or name" />
	</Field>
	<Field label="Scope" for="model-scope" class="w-full sm:w-52">
		<Select
			id="model-scope"
			bind:value={filterScope}
			options={scopeOptions.map((o) => ({ value: o, label: o ? sentence(o) : 'Any scope' }))}
		/>
	</Field>
	<Field label="Runtime" for="model-runtime" class="w-full sm:w-40">
		<Select
			id="model-runtime"
			bind:value={filterRuntime}
			options={runtimeOptions.map((o) => ({ value: o, label: o || 'Any runtime' }))}
		/>
	</Field>
	<Field label="Family" for="model-family" class="w-full sm:w-40">
		<Input id="model-family" bind:value={filterFamily} placeholder="yolo, nanodet" />
	</Field>
	<Button variant="ghost" onclick={clearFilters}>Reset</Button>
</div>

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}

{#if loading && !data}
	<div class="flex justify-center py-12"><Spinner size={32} /></div>
{:else if data && data.items.length === 0}
	<Panel><EmptyState icon={Boxes} title="No models match">Change or reset the filters.</EmptyState></Panel>
{:else if data}
	<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 lg:grid-cols-3">
		{#each data.items as model (model.id)}
			<ModelCard {model} />
		{/each}
	</div>

	{#if data.pages > 1}
		<div class="flex items-center justify-center gap-2">
			<Button size="sm" disabled={currentPage <= 1} onclick={() => (currentPage = Math.max(1, currentPage - 1))}>Previous</Button>
			<span class="num text-sm text-ink-muted">Page {data.page} of {data.pages}, {data.total} models</span>
			<Button
				size="sm"
				disabled={currentPage >= data.pages}
				onclick={() => (currentPage = Math.min(data?.pages ?? 1, currentPage + 1))}>Next</Button
			>
		</div>
	{/if}
{/if}

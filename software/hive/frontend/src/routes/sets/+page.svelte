<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type SetInstanceSummary } from '$lib/api';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';
	import CompletenessBar from '$lib/components/sets/CompletenessBar.svelte';
	import { Alert, Button } from '$lib/components/primitives';
	import Plus from 'lucide-svelte/icons/plus';

	type SetResult = { set_num: string; name: string; year: number; num_parts: number; img_url: string | null };

	let instances = $state<SetInstanceSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let showArchived = $state(false);

	let addOpen = $state(false);
	let picked = $state<SetResult | null>(null);
	let label = $state('');
	let includeSpares = $state(false);
	let notes = $state('');
	let creating = $state(false);
	let createError = $state<string | null>(null);

	$effect(() => {
		void load(showArchived);
	});

	async function load(includeArchived: boolean) {
		loading = true;
		error = null;
		try {
			instances = await api.getSetInstances(includeArchived);
		} catch (e: any) {
			error = e.error || 'Failed to load set instances';
		} finally {
			loading = false;
		}
	}

	function openAdd() {
		picked = null;
		label = '';
		includeSpares = false;
		notes = '';
		createError = null;
		addOpen = true;
	}

	function pickSet(set: SetResult) {
		picked = set;
		label = set.name;
	}

	async function create() {
		if (!picked) return;
		creating = true;
		createError = null;
		try {
			const created = await api.createSetInstance({
				set_num: picked.set_num,
				label: label.trim() || null,
				include_spares: includeSpares,
				notes: notes.trim() || null
			});
			addOpen = false;
			goto(`/sets/${created.id}`);
		} catch (e: any) {
			createError = e.error || 'Failed to add the set';
		} finally {
			creating = false;
		}
	}

	const STATUS_CLASS: Record<SetInstanceSummary['status'], string> = {
		open: 'text-text-muted',
		complete: 'text-success',
		archived: 'text-warning-strong'
	};
</script>

<svelte:head>
	<title>My Sets - Hive</title>
</svelte:head>

<div class="mb-6 flex flex-wrap items-start justify-between gap-4">
	<div>
		<h1 class="text-2xl font-bold text-text">My Sets</h1>
		<p class="mt-1 text-sm text-text-muted">
			Each entry is one physical copy of a set you are extracting. Progress stays with the copy across runs and machines.
		</p>
	</div>
	<div class="flex items-center gap-3">
		<label class="flex items-center gap-1.5 text-xs text-text-muted">
			<input type="checkbox" bind:checked={showArchived} class="accent-primary" />
			Show archived
		</label>
		<Button onclick={openAdd}><Plus size={14} /> Add set</Button>
	</div>
</div>

{#if error}
	<div class="mb-4"><Alert variant="danger">{error}</Alert></div>
{/if}

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if instances.length === 0}
	<div class="border border-border bg-surface p-6 text-sm text-text-muted">
		No sets yet. Add one to start tracking which parts your sorter has found.
	</div>
{:else}
	<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
		{#each instances as instance (instance.id)}
			<a href={`/sets/${instance.id}`} class="flex gap-4 border border-border bg-surface p-4 transition-colors hover:border-text-muted">
				{#if instance.set_meta.img_url}
					<img src={instance.set_meta.img_url} alt="" class="h-20 w-20 shrink-0 object-contain" />
				{:else}
					<div class="flex h-20 w-20 shrink-0 items-center justify-center bg-bg text-xs text-text-muted">N/A</div>
				{/if}
				<div class="min-w-0 flex-1">
					<div class="flex items-start justify-between gap-2">
						<h2 class="truncate text-sm font-semibold text-text">{instance.label}</h2>
						<span class="shrink-0 text-[10px] font-medium uppercase tracking-wide {STATUS_CLASS[instance.status]}">{instance.status}</span>
					</div>
					<p class="mt-0.5 truncate text-xs text-text-muted">
						<span class="font-mono">{instance.set_num}</span>
						{#if instance.set_meta.name} · {instance.set_meta.name}{/if}
						{#if instance.set_meta.year} · {instance.set_meta.year}{/if}
					</p>
					<div class="mt-3">
						<CompletenessBar found={instance.total_found} needed={instance.total_needed} pct={instance.pct} compact />
					</div>
				</div>
			</a>
		{/each}
	</div>
{/if}

<Modal open={addOpen} title="Add a set" onclose={() => (addOpen = false)}>
	{#if !picked}
		<SetSearch onSelect={pickSet} />
	{:else}
		<div class="flex items-center gap-3 border border-border p-2">
			{#if picked.img_url}
				<img src={picked.img_url} alt="" class="h-24 w-24 shrink-0 object-contain" />
			{/if}
			<div class="min-w-0 flex-1">
				<div class="truncate text-sm font-medium text-text">{picked.name}</div>
				<div class="text-xs text-text-muted">{picked.set_num} · {picked.year} · {picked.num_parts} parts</div>
			</div>
			<button type="button" class="text-xs text-text-muted hover:text-primary" onclick={() => (picked = null)}>Change</button>
		</div>
		<label class="mt-4 block text-xs font-medium text-text-muted" for="set-label">Label</label>
		<input id="set-label" type="text" bind:value={label} placeholder="e.g. Space Shuttle, box in the basement"
			class="mt-1 w-full border border-border bg-surface px-3 py-2 text-sm text-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
		<label class="mt-3 flex items-center gap-2 text-sm text-text">
			<input type="checkbox" bind:checked={includeSpares} class="accent-primary" />
			Include spare parts
		</label>
		<label class="mt-3 block text-xs font-medium text-text-muted" for="set-notes">Notes</label>
		<textarea id="set-notes" bind:value={notes} rows="2"
			class="mt-1 w-full border border-border bg-surface px-3 py-2 text-sm text-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"></textarea>
		{#if createError}
			<div class="mt-3"><Alert variant="danger">{createError}</Alert></div>
		{/if}
		<div class="mt-4 flex justify-end gap-2">
			<Button variant="secondary" onclick={() => (addOpen = false)}>Cancel</Button>
			<Button onclick={create} loading={creating}>Add set</Button>
		</div>
	{/if}
</Modal>

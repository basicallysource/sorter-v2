<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api, type SetInstanceDetail, type SetInstancePart } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import CompletenessBar from '$lib/components/sets/CompletenessBar.svelte';
	import { Alert, Button } from '$lib/components/primitives';
	import Archive from 'lucide-svelte/icons/archive';
	import ArchiveRestore from 'lucide-svelte/icons/archive-restore';
	import Download from 'lucide-svelte/icons/download';
	import Minus from 'lucide-svelte/icons/minus';
	import Pencil from 'lucide-svelte/icons/pencil';
	import Plus from 'lucide-svelte/icons/plus';

	const id = $derived(page.params.id ?? '');

	let instance = $state<SetInstanceDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let editing = $state(false);
	let label = $state('');
	let notes = $state('');
	let saving = $state(false);
	let confirmArchive = $state(false);
	let archiving = $state(false);

	let filter = $state<'all' | 'missing'>('missing');
	let query = $state('');
	let busyKey = $state<string | null>(null);

	$effect(() => {
		void load(id);
	});

	async function load(instanceId: string) {
		loading = true;
		error = null;
		try {
			instance = await api.getSetInstance(instanceId);
		} catch (e: any) {
			error = e.error || 'Failed to load the set';
		} finally {
			loading = false;
		}
	}

	function keyOf(part: SetInstancePart): string {
		return `${part.part_num}/${part.color_id}`;
	}

	const visibleParts = $derived.by(() => {
		if (!instance) return [];
		const q = query.trim().toLowerCase();
		return instance.parts.filter((part) => {
			if (filter === 'missing' && part.quantity_missing === 0) return false;
			if (!q) return true;
			return (
				part.part_num.toLowerCase().includes(q) ||
				(part.part_name ?? '').toLowerCase().includes(q) ||
				(part.color_name ?? '').toLowerCase().includes(q)
			);
		});
	});

	const missingCount = $derived(instance ? instance.parts.filter((p) => p.quantity_missing > 0).length : 0);

	function startEdit() {
		if (!instance) return;
		label = instance.label;
		notes = instance.notes ?? '';
		editing = true;
	}

	async function saveEdit() {
		if (!instance) return;
		saving = true;
		error = null;
		try {
			const updated = await api.updateSetInstance(instance.id, { label: label.trim(), notes: notes.trim() });
			instance = { ...instance, ...updated };
			editing = false;
		} catch (e: any) {
			error = e.error || 'Failed to save';
		} finally {
			saving = false;
		}
	}

	async function archive() {
		if (!instance) return;
		archiving = true;
		try {
			await api.archiveSetInstance(instance.id);
			goto('/sets');
		} catch (e: any) {
			error = e.error || 'Failed to archive';
			archiving = false;
			confirmArchive = false;
		}
	}

	async function restore() {
		if (!instance) return;
		archiving = true;
		error = null;
		try {
			const updated = await api.restoreSetInstance(instance.id);
			instance = { ...instance, ...updated };
		} catch (e: any) {
			error = e.error || 'Failed to restore';
		} finally {
			archiving = false;
		}
	}

	async function setFound(part: SetInstancePart, quantity: number) {
		if (!instance) return;
		const clamped = Math.max(0, Math.min(part.quantity_needed, Math.round(quantity)));
		if (clamped === part.quantity_found) return;
		busyKey = keyOf(part);
		error = null;
		try {
			const updated = await api.adjustSetInstancePart(instance.id, part.part_num, part.color_id, clamped);
			const parts = instance.parts.map((p) => (keyOf(p) === keyOf(updated) ? updated : p));
			const total_found = parts.reduce((sum, p) => sum + p.quantity_found, 0);
			const total_needed = instance.total_needed;
			const pct = total_needed > 0 ? Math.round((total_found / total_needed) * 1000) / 10 : 0;
			const status = instance.status === 'archived' ? 'archived' : total_needed > 0 && total_found >= total_needed ? 'complete' : 'open';
			instance = { ...instance, parts, total_found, pct, status };
		} catch (e: any) {
			error = e.error || 'Failed to update the part';
		} finally {
			busyKey = null;
		}
	}

	function onFoundInput(part: SetInstancePart, event: Event) {
		const value = Number((event.currentTarget as HTMLInputElement).value);
		if (Number.isFinite(value)) void setFound(part, value);
	}
</script>

<svelte:head>
	<title>{instance ? instance.label : 'Set'} - Hive</title>
</svelte:head>

<div class="mx-auto max-w-5xl py-8 sm:px-4">
	<a href="/sets" class="text-sm text-text-muted hover:text-primary hover:underline">&larr; My Sets</a>

	{#if loading}
		<div class="mt-8 flex justify-center"><Spinner size={32} /></div>
	{:else if error && !instance}
		<div class="mt-6"><Alert variant="danger">{error}</Alert></div>
	{:else if instance}
		{#if error}
			<div class="mt-4"><Alert variant="danger">{error}</Alert></div>
		{/if}

		<header class="mt-3 border border-border bg-surface p-5">
			<div class="flex flex-wrap items-start gap-5">
				{#if instance.set_meta.img_url}
					<img src={instance.set_meta.img_url} alt="" class="h-28 w-28 shrink-0 object-contain" />
				{/if}
				<div class="min-w-0 flex-1">
					{#if editing}
						<input type="text" bind:value={label} aria-label="Label"
							class="w-full border border-border bg-surface px-3 py-2 text-lg font-semibold text-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
						<textarea bind:value={notes} rows="2" placeholder="Notes" aria-label="Notes"
							class="mt-2 w-full border border-border bg-surface px-3 py-2 text-sm text-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"></textarea>
						<div class="mt-2 flex gap-2">
							<Button size="sm" onclick={saveEdit} loading={saving}>Save</Button>
							<Button size="sm" variant="secondary" onclick={() => (editing = false)}>Cancel</Button>
						</div>
					{:else}
						<div class="flex items-center gap-2">
							<h1 class="truncate text-xl font-semibold text-text">{instance.label}</h1>
							<span class="text-[10px] font-medium uppercase tracking-wider {instance.status === 'complete' ? 'text-success' : instance.status === 'archived' ? 'text-warning-strong' : 'text-text-muted'}">{instance.status}</span>
							<button type="button" class="p-1 text-text-muted hover:text-primary" onclick={startEdit} aria-label="Edit label and notes"><Pencil size={14} /></button>
						</div>
						<p class="mt-1 text-sm text-text-muted">
							<span class="font-mono">{instance.set_num}</span>
							{#if instance.set_meta.name} · {instance.set_meta.name}{/if}
							{#if instance.set_meta.year} · {instance.set_meta.year}{/if}
							{#if instance.include_spares} · incl. spares{/if}
						</p>
						{#if instance.notes}
							<p class="mt-2 whitespace-pre-line text-sm text-text">{instance.notes}</p>
						{/if}
					{/if}
					<div class="mt-4 max-w-md">
						<CompletenessBar found={instance.total_found} needed={instance.total_needed} pct={instance.pct} />
					</div>
				</div>
				<div class="flex shrink-0 flex-col gap-2">
					<a href={api.setInstanceWantedListUrl(instance.id)} download
						class="flex items-center gap-1.5 border border-border bg-surface px-2.5 py-1 text-xs text-text hover:bg-bg">
						<Download size={14} /> Wanted list (BrickLink XML)
					</a>
					{#if instance.status === 'archived'}
						<Button size="sm" variant="secondary" onclick={restore} loading={archiving}><ArchiveRestore size={14} /> Restore</Button>
					{:else if confirmArchive}
						<div class="flex gap-1">
							<Button size="sm" variant="danger" onclick={archive} loading={archiving}>Archive</Button>
							<Button size="sm" variant="secondary" onclick={() => (confirmArchive = false)}>Keep</Button>
						</div>
					{:else}
						<Button size="sm" variant="secondary" onclick={() => (confirmArchive = true)}><Archive size={14} /> Archive</Button>
					{/if}
				</div>
			</div>
		</header>

		<section class="mt-4 border border-border bg-surface">
			<div class="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
				<div class="flex gap-1 text-xs">
					<button type="button" onclick={() => (filter = 'missing')}
						class="px-2.5 py-1 {filter === 'missing' ? 'bg-primary text-white' : 'border border-border text-text hover:bg-bg'}">
						Missing ({missingCount})
					</button>
					<button type="button" onclick={() => (filter = 'all')}
						class="px-2.5 py-1 {filter === 'all' ? 'bg-primary text-white' : 'border border-border text-text hover:bg-bg'}">
						All ({instance.parts.length})
					</button>
				</div>
				<input type="search" bind:value={query} placeholder="Filter by part, name or colour"
					class="w-64 border border-border bg-surface px-3 py-1.5 text-xs text-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
			</div>

			{#if visibleParts.length === 0}
				<div class="p-6 text-sm text-text-muted">
					{filter === 'missing' && !query ? 'Nothing missing. This copy is complete.' : 'No parts match.'}
				</div>
			{:else}
				<table class="w-full text-sm">
					<thead class="text-left text-[11px] uppercase tracking-wide text-text-muted">
						<tr class="border-b border-border">
							<th class="px-4 py-2 font-medium" colspan="2">Part</th>
							<th class="px-2 py-2 font-medium">Colour</th>
							<th class="px-2 py-2 text-right font-medium">Needed</th>
							<th class="px-2 py-2 text-center font-medium">Found</th>
							<th class="px-4 py-2 text-right font-medium">Missing</th>
						</tr>
					</thead>
					<tbody>
						{#each visibleParts as part (keyOf(part))}
							{@const busy = busyKey === keyOf(part)}
							<tr class="border-b border-border last:border-b-0">
								<td class="w-12 px-4 py-1.5">
									{#if part.img_url}
										<img src={part.img_url} alt="" class="h-8 w-8 object-contain" />
									{/if}
								</td>
								<td class="py-1.5 pr-2">
									<div class="font-mono text-xs text-text">{part.part_num}</div>
									{#if part.part_name}<div class="truncate text-xs text-text-muted">{part.part_name}</div>{/if}
								</td>
								<td class="px-2 py-1.5 text-xs text-text-muted">{part.color_name ?? part.color_id}</td>
								<td class="px-2 py-1.5 text-right tabular-nums">{part.quantity_needed}</td>
								<td class="px-2 py-1.5">
									<div class="flex items-center justify-center gap-1">
										<button type="button" class="border border-border p-1 text-text hover:bg-bg disabled:opacity-40" aria-label="One less"
											disabled={busy || part.quantity_found === 0} onclick={() => setFound(part, part.quantity_found - 1)}><Minus size={12} /></button>
										<input type="number" min="0" max={part.quantity_needed} value={part.quantity_found} disabled={busy} aria-label="Found"
											onchange={(e) => onFoundInput(part, e)}
											class="w-14 border border-border bg-surface px-1 py-0.5 text-center text-sm tabular-nums text-text focus:border-primary focus:outline-none" />
										<button type="button" class="border border-border p-1 text-text hover:bg-bg disabled:opacity-40" aria-label="One more"
											disabled={busy || part.quantity_found >= part.quantity_needed} onclick={() => setFound(part, part.quantity_found + 1)}><Plus size={12} /></button>
									</div>
								</td>
								<td class="px-4 py-1.5 text-right tabular-nums {part.quantity_missing > 0 ? 'text-primary' : 'text-success'}">{part.quantity_missing}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>
	{/if}
</div>

<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type AccessWindow } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import { Button } from '$lib/components/primitives';

	let windows = $state<AccessWindow[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let savingKey = $state<string | null>(null);
	let flash = $state<string | null>(null);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		load();
	});

	async function load() {
		loading = true;
		error = null;
		try {
			const resp = await api.getAccessWindows();
			windows = resp.windows;
		} catch (e: any) {
			error = e.error || 'Failed to load access windows';
		} finally {
			loading = false;
		}
	}

	function keyOf(w: AccessWindow) {
		return `${w.role}/${w.entity}`;
	}

	async function save(w: AccessWindow) {
		savingKey = keyOf(w);
		error = null;
		flash = null;
		try {
			const resp = await api.updateAccessWindow(w.role, w.entity, {
				anchor: w.anchor,
				size: w.size,
				offset: w.offset
			});
			windows = resp.windows;
			flash = `Saved ${w.role} / ${entityLabel(w.entity)}.`;
		} catch (e: any) {
			error = e.error || 'Failed to save window';
		} finally {
			savingKey = null;
		}
	}

	function entityLabel(entity: string) {
		return entity === 'piece' ? 'Pieces' : 'Channel crops';
	}
</script>

<svelte:head>
	<title>Access Windows - Hive</title>
</svelte:head>

<div class="mb-2 flex items-center justify-between">
	<h1 class="text-2xl font-bold text-text">Access Windows</h1>
	<span class="text-sm text-text-muted">Admins are unrestricted</span>
</div>

<p class="mb-6 max-w-3xl text-sm text-text-muted">
	Bounds how much of the accumulating piece-bbox dataset each non-admin role can see and download.
	A window is a contiguous slice ordered by upload time. <strong class="text-text">Oldest</strong> anchors
	the slice to the start of the dataset, so it stays pinned to the same rows as new data arrives —
	intended for plain members. <strong class="text-text">Newest</strong> anchors to the end, so it rolls
	forward with fresh uploads — intended for reviewers. <strong class="text-text">Size</strong> is how many
	rows are visible; <strong class="text-text">offset</strong> skips that many rows from the anchor.
	Admins bypass all of this.
</p>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}
{#if flash}
	<div class="mb-4 bg-success/[0.08] p-3 text-sm text-success">{flash}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12">
		<Spinner />
	</div>
{:else}
	<div class="overflow-x-auto border border-border bg-surface">
		<table class="min-w-full divide-y divide-border">
			<thead class="bg-bg">
				<tr>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Role</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Data</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Anchor</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Size</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Offset</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Source</th>
					<th class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each windows as w (keyOf(w))}
					<tr class="hover:bg-bg">
						<td class="whitespace-nowrap px-6 py-4 text-sm font-medium capitalize text-text">{w.role}</td>
						<td class="whitespace-nowrap px-6 py-4 text-sm text-text">{entityLabel(w.entity)}</td>
						<td class="whitespace-nowrap px-6 py-4">
							<select
								bind:value={w.anchor}
								class="border border-border bg-surface px-2 py-1 text-sm text-text"
							>
								<option value="oldest">oldest (pinned)</option>
								<option value="newest">newest (rolling)</option>
							</select>
						</td>
						<td class="whitespace-nowrap px-6 py-4">
							<input
								type="number"
								min="0"
								bind:value={w.size}
								class="w-28 border border-border bg-surface px-2 py-1 text-sm text-text"
							/>
						</td>
						<td class="whitespace-nowrap px-6 py-4">
							<input
								type="number"
								min="0"
								bind:value={w.offset}
								class="w-24 border border-border bg-surface px-2 py-1 text-sm text-text"
							/>
						</td>
						<td class="whitespace-nowrap px-6 py-4">
							<Badge
								text={w.source}
								variant={w.source === 'override' ? 'info' : 'neutral'}
							/>
						</td>
						<td class="whitespace-nowrap px-6 py-4 text-right">
							<Button
								variant="primary"
								size="sm"
								loading={savingKey === keyOf(w)}
								onclick={() => save(w)}
							>
								Save
							</Button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

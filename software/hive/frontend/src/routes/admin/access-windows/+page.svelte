<script lang="ts">
	import { sentence } from '$lib/text';
	import { auth } from '$lib/auth.svelte';
	import { api, type AccessWindow } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';

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
	<h1 class="text-2xl font-bold text-ink">Access Windows</h1>
	<span class="text-sm text-ink-muted">Admins are unrestricted</span>
</div>

<p class="mb-6 max-w-3xl text-sm text-ink-muted">
	Bounds how much of the accumulating piece-bbox dataset each non-admin role can see and download.
	A window is a contiguous slice ordered by upload time. <strong class="text-ink">Oldest</strong> anchors
	the slice to the start of the dataset, so it stays pinned to the same rows as new data arrives —
	intended for plain members. <strong class="text-ink">Newest</strong> anchors to the end, so it rolls
	forward with fresh uploads — intended for reviewers. <strong class="text-ink">Size</strong> is how many
	rows are visible; <strong class="text-ink">offset</strong> skips that many rows from the anchor.
	Admins bypass all of this.
</p>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary-ink">{error}</div>
{/if}
{#if flash}
	<div class="mb-4 bg-success/[0.08] p-3 text-sm text-success-ink">{flash}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12">
		<Spinner size={32} />
	</div>
{:else}
	<div class="overflow-x-auto border border-line bg-surface">
		<table class="min-w-full divide-y divide-line">
			<thead class="bg-well">
				<tr>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Role</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Data</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Anchor</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Size</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Offset</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Source</th>
					<th class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-line">
				{#each windows as w (keyOf(w))}
					<tr class="hover:bg-hover">
						<td class="whitespace-nowrap px-6 py-4 text-sm font-medium capitalize text-ink">{w.role}</td>
						<td class="whitespace-nowrap px-6 py-4 text-sm text-ink">{entityLabel(w.entity)}</td>
						<td class="whitespace-nowrap px-6 py-4">
							<select
								bind:value={w.anchor}
								class="border border-line bg-surface px-2 py-1 text-sm text-ink"
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
								class="w-28 border border-line bg-surface px-2 py-1 text-sm text-ink"
							/>
						</td>
						<td class="whitespace-nowrap px-6 py-4">
							<input
								type="number"
								min="0"
								bind:value={w.offset}
								class="w-24 border border-line bg-surface px-2 py-1 text-sm text-ink"
							/>
						</td>
						<td class="whitespace-nowrap px-6 py-4">
							<Badge tone={w.source === 'override' ? 'info' : 'neutral'}>{sentence(w.source)}</Badge>
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

<script lang="ts">
	import { Button, Input, SelectMenu } from '$lib/components/primitives';
	import Modal from '$lib/components/Modal.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { requestBackendRestart, waitForBackend } from '$lib/backend';
	import {
		fetchBinLayouts,
		fetchActiveBinLayout,
		applyBinLayout,
		saveBinLayout,
		createBinLayout,
		renameBinLayout,
		deleteBinLayout,
		type BinLayoutRecord
	} from '$lib/api/bin-layouts';
	import { onMount } from 'svelte';
	import { Check, Loader2, Pencil, Trash2 } from 'lucide-svelte';

	let {
		baseUrl,
		profileId = null,
		profileName = ''
	}: { baseUrl: string; profileId?: string | null; profileName?: string } = $props();

	let layouts = $state<BinLayoutRecord[]>([]);
	let active = $state<BinLayoutRecord | null>(null);
	let busy = $state(false);
	let restarting = $state(false);
	let error = $state<string | null>(null);
	let status = $state('');
	let pickerOpen = $state(false);

	let switchOpen = $state(false);
	let saveAsOpen = $state(false);
	let renameOpen = $state(false);
	let deleteOpen = $state(false);
	let target = $state<BinLayoutRecord | null>(null);
	let draftName = $state('');

	const isDirty = $derived(active?.dirty ?? false);

	async function reload() {
		try {
			const [list, act] = await Promise.all([
				fetchBinLayouts(baseUrl, profileId),
				fetchActiveBinLayout(baseUrl)
			]);
			layouts = list.layouts;
			active = act.active;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load bin layouts';
		}
	}

	onMount(() => {
		void reload();
		const interval = setInterval(() => void reload(), 2000);
		return () => clearInterval(interval);
	});

	// Reload when the active profile changes (layouts are scoped to it).
	let lastProfile = $state<string | null | undefined>(undefined);
	$effect(() => {
		if (profileId !== lastProfile) {
			lastProfile = profileId;
			void reload();
		}
	});

	function openSwitch(layout: BinLayoutRecord) {
		pickerOpen = false;
		if (layout.is_active) return;
		target = layout;
		switchOpen = true;
	}

	function openSaveAs() {
		draftName = '';
		saveAsOpen = true;
	}

	function openRename(layout: BinLayoutRecord) {
		pickerOpen = false;
		target = layout;
		draftName = layout.name;
		renameOpen = true;
	}

	function openDelete(layout: BinLayoutRecord) {
		pickerOpen = false;
		target = layout;
		deleteOpen = true;
	}

	async function run(action: () => Promise<void>, successMsg: string) {
		busy = true;
		error = null;
		status = '';
		try {
			await action();
			status = successMsg;
			await reload();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Something went wrong';
		} finally {
			busy = false;
		}
	}

	async function confirmSwitch() {
		const layout = target;
		switchOpen = false;
		if (!layout) return;
		busy = true;
		error = null;
		status = '';
		try {
			const res = await applyBinLayout(baseUrl, layout.id);
			if (res.restart_required) {
				restarting = true;
				status = `Switching to "${layout.name}" — restarting…`;
				await requestBackendRestart(baseUrl);
				await waitForBackend(baseUrl, { maxAttempts: 60 });
			}
			await reload();
			status = `Switched to "${layout.name}".`;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to switch bin layout';
		} finally {
			busy = false;
			restarting = false;
		}
	}

	async function confirmSaveAs() {
		const name = draftName.trim();
		saveAsOpen = false;
		if (!name) return;
		await run(() => createBinLayout(baseUrl, name).then(() => {}), `Saved current bins as "${name}".`);
	}

	async function confirmRename() {
		const layout = target;
		const name = draftName.trim();
		renameOpen = false;
		if (!layout || !name) return;
		await run(() => renameBinLayout(baseUrl, layout.id, name).then(() => {}), `Renamed to "${name}".`);
	}

	async function confirmDelete() {
		const layout = target;
		deleteOpen = false;
		if (!layout) return;
		await run(() => deleteBinLayout(baseUrl, layout.id).then(() => {}), `Deleted "${layout.name}".`);
	}

	async function saveChanges() {
		const layout = active;
		if (!layout) return;
		await run(() => saveBinLayout(baseUrl, layout.id).then(() => {}), 'Saved changes to the current bin layout.');
	}
</script>

<div class="mb-4 border border-border bg-surface px-4 py-3">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="min-w-0">
			<div class="text-sm font-medium text-text">Bin layout</div>
			<div class="mt-0.5 text-sm text-text-muted">
				Saved bin configurations for <span class="text-text">{profileName || 'this profile'}</span>.
				Switch between them; bin contents are kept unless you empty the bins.
			</div>
		</div>
		<div class="flex items-center gap-2">
			<SelectMenu bind:open={pickerOpen} searchable={false} width={300} align="right">
				{#snippet trigger()}
					<span
						class="inline-flex items-center gap-2 border border-border bg-white px-3 py-2 text-sm text-text transition-colors hover:bg-surface"
					>
						{#if restarting}
							<Loader2 size={14} class="animate-spin" />
						{/if}
						{active?.name ?? 'No layout'}
						{#if isDirty}<span class="text-warning">• unsaved</span>{/if}
					</span>
				{/snippet}
				{#if layouts.length === 0}
					<div class="px-3 py-2 text-sm text-text-muted">No saved layouts for this profile.</div>
				{/if}
				{#each layouts as layout (layout.id)}
					<div
						class="flex items-center justify-between gap-2 border-b border-border bg-white px-3 py-2 text-sm last:border-b-0 hover:bg-surface"
					>
						<button
							type="button"
							class="flex min-w-0 flex-1 items-center gap-2 text-left text-text disabled:opacity-60"
							disabled={busy || layout.is_active}
							onclick={() => openSwitch(layout)}
						>
							{#if layout.is_active}
								<Check size={14} class="shrink-0 text-success" />
							{:else}
								<span class="w-[14px] shrink-0"></span>
							{/if}
							<span class="truncate">{layout.name}</span>
						</button>
						<div class="flex shrink-0 items-center gap-1">
							<button
								type="button"
								class="p-1 text-text-muted hover:text-text"
								title="Rename"
								onclick={() => openRename(layout)}
							>
								<Pencil size={13} />
							</button>
							<button
								type="button"
								class="p-1 text-text-muted hover:text-danger disabled:opacity-40"
								title={layout.is_active ? 'Cannot delete the active layout' : 'Delete'}
								disabled={layout.is_active}
								onclick={() => openDelete(layout)}
							>
								<Trash2 size={13} />
							</button>
						</div>
					</div>
				{/each}
			</SelectMenu>
			<Button variant="secondary" size="sm" disabled={busy || !isDirty} onclick={() => void saveChanges()}>
				Save changes
			</Button>
			<Button variant="secondary" size="sm" disabled={busy} onclick={openSaveAs}>Save as new</Button>
		</div>
	</div>

	{#if status}<div class="mt-2"><StatusBanner message={status} variant="success" /></div>{/if}
	{#if error}<div class="mt-2"><StatusBanner message={error} variant="error" /></div>{/if}
</div>

<Modal bind:open={switchOpen} title="Switch bin layout">
	<div class="space-y-4">
		<p class="text-sm text-text">
			Switch to <span class="font-medium">{target?.name}</span>? This restarts the backend
			(a few seconds). Bin contents are kept.
		</p>
		<div class="flex justify-end gap-2">
			<Button variant="ghost" size="sm" onclick={() => (switchOpen = false)}>Cancel</Button>
			<Button variant="primary" size="sm" onclick={() => void confirmSwitch()}>Switch</Button>
		</div>
	</div>
</Modal>

<Modal bind:open={saveAsOpen} title="Save as new bin layout">
	<div class="space-y-4">
		<Input type="text" placeholder="Layout name" bind:value={draftName} />
		<div class="flex justify-end gap-2">
			<Button variant="ghost" size="sm" onclick={() => (saveAsOpen = false)}>Cancel</Button>
			<Button variant="primary" size="sm" disabled={!draftName.trim()} onclick={() => void confirmSaveAs()}>
				Save
			</Button>
		</div>
	</div>
</Modal>

<Modal bind:open={renameOpen} title="Rename bin layout">
	<div class="space-y-4">
		<Input type="text" placeholder="Layout name" bind:value={draftName} />
		<div class="flex justify-end gap-2">
			<Button variant="ghost" size="sm" onclick={() => (renameOpen = false)}>Cancel</Button>
			<Button variant="primary" size="sm" disabled={!draftName.trim()} onclick={() => void confirmRename()}>
				Rename
			</Button>
		</div>
	</div>
</Modal>

<Modal bind:open={deleteOpen} title="Delete bin layout">
	<div class="space-y-4">
		<p class="text-sm text-text">
			Delete <span class="font-medium">{target?.name}</span>? This can't be undone.
		</p>
		<div class="flex justify-end gap-2">
			<Button variant="ghost" size="sm" onclick={() => (deleteOpen = false)}>Cancel</Button>
			<Button variant="danger" size="sm" onclick={() => void confirmDelete()}>Delete</Button>
		</div>
	</div>
</Modal>

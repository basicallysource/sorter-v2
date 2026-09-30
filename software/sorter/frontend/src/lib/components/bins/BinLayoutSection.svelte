<script lang="ts">
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';
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
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';

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
	let dropdownOpen = $state(false);

	let switchOpen = $state(false);
	let saveAsOpen = $state(false);
	let renameOpen = $state(false);
	let deleteOpen = $state(false);
	let target = $state<BinLayoutRecord | null>(null);
	let draftName = $state('');

	const isDirty = $derived(active?.dirty ?? false);

	function profileLabel(id: string | null): string {
		return (id ?? '').replace(/\.json$/, '') || 'no profile';
	}

	async function reload() {
		try {
			const [list, act] = await Promise.all([
				fetchBinLayouts(baseUrl),
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

	function openSwitch(layout: BinLayoutRecord) {
		dropdownOpen = false;
		if (layout.is_active) return;
		target = layout;
		switchOpen = true;
	}

	function openSaveAs() {
		dropdownOpen = false;
		draftName = '';
		saveAsOpen = true;
	}

	function openRename(layout: BinLayoutRecord) {
		dropdownOpen = false;
		target = layout;
		draftName = layout.name;
		renameOpen = true;
	}

	function openDelete(layout: BinLayoutRecord) {
		dropdownOpen = false;
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

<Panel
	title="Bin layout"
	description="Saved bin configurations. Switch between them; bin contents are kept unless you empty the bins."
>
	<div class="flex flex-col gap-3">
		<div class="flex flex-wrap items-center gap-2">
		<Popover label="Bin layouts" bind:open={dropdownOpen} width="22rem" padded={false}>
			{#snippet trigger(props)}
				<Button {...props} class="w-64 max-w-full" disabled={layouts.length === 0 && !active}>
					<span class="flex w-full min-w-0 items-center justify-between gap-2">
						<span class="flex min-w-0 items-center gap-2">
							<span class="truncate">{active?.name ?? 'No layout'}</span>
							{#if isDirty}<Badge tone="warning">Unsaved</Badge>{/if}
						</span>
						<ChevronDown size={16} class="shrink-0" />
					</span>
				</Button>
			{/snippet}
			<p class="px-3 py-2 text-sm text-ink-muted">
				Each layout belongs to a profile and only works with that profile.
			</p>
			{#if layouts.length === 0}
				<p class="border-t border-line px-3 py-2 text-sm text-ink-muted">No saved layouts yet.</p>
			{:else}
				<ul class="divide-y divide-line border-t border-line">
					{#each layouts as layout (layout.id)}
						{@const matches = layout.profile_id === profileId}
						<li class="flex items-center gap-1 py-1 pr-1 pl-1 {matches ? '' : 'opacity-50'}">
							<button
								type="button"
								class="flex min-h-(--size-menu-item) min-w-0 flex-1 items-center gap-2.5 rounded-item px-2 text-left hover:bg-hover disabled:pointer-events-none"
								disabled={busy || layout.is_active || !matches}
								title={matches ? undefined : 'Switch to this layout’s profile first'}
								onclick={() => openSwitch(layout)}
							>
								<Check size={16} class="shrink-0 text-success-ink {layout.is_active ? '' : 'invisible'}" />
								<span class="min-w-0">
									<span class="block truncate text-sm font-medium text-ink">{layout.name}</span>
									<span class="block truncate font-mono text-xs text-ink-muted">
										{profileLabel(layout.profile_id)}
									</span>
								</span>
							</button>
							<Button size="sm" variant="ghost" icon={Pencil} label="Rename {layout.name}" onclick={() => openRename(layout)} />
							<Button
								size="sm"
								variant="ghost"
								icon={Trash2}
								label={layout.is_active ? 'The active layout cannot be deleted' : `Delete ${layout.name}`}
								disabled={layout.is_active}
								onclick={() => openDelete(layout)}
							/>
						</li>
					{/each}
				</ul>
			{/if}
		</Popover>
		<Button disabled={busy} onclick={openSaveAs}>Save as new</Button>
		<Button variant="primary" disabled={busy || !isDirty} onclick={() => void saveChanges()}>
			Save changes
		</Button>
		</div>
		{#if status}<Alert tone="success">{status}</Alert>{/if}
		{#if error}<Alert tone="danger">{error}</Alert>{/if}
	</div>
</Panel>

<Modal bind:open={switchOpen} title="Switch the bin layout" size="sm">
	<p>
		Switch to <span class="font-medium">{target?.name}</span>? This restarts the backend, which takes
		a few seconds. Bin contents are kept.
	</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (switchOpen = false)}>Cancel</Button>
		<Button variant="primary" onclick={() => void confirmSwitch()}>Switch</Button>
	{/snippet}
</Modal>

<Modal open={restarting} title="Switching the bin layout" size="sm" dismissible={false} status="Restarting the backend">
	<p>This page carries on by itself when the backend is back.</p>
</Modal>

<Modal bind:open={saveAsOpen} title="Save as a new bin layout" size="sm">
	<Input aria-label="Layout name" placeholder="Layout name" bind:value={draftName} />
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (saveAsOpen = false)}>Cancel</Button>
		<Button variant="primary" disabled={!draftName.trim()} onclick={() => void confirmSaveAs()}>Save</Button>
	{/snippet}
</Modal>

<Modal bind:open={renameOpen} title="Rename the bin layout" size="sm">
	<Input aria-label="Layout name" placeholder="Layout name" bind:value={draftName} />
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (renameOpen = false)}>Cancel</Button>
		<Button variant="primary" disabled={!draftName.trim()} onclick={() => void confirmRename()}>Rename</Button>
	{/snippet}
</Modal>

<Modal bind:open={deleteOpen} title="Delete the bin layout" size="sm">
	<p>Delete <span class="font-medium">{target?.name}</span>? This cannot be undone.</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (deleteOpen = false)}>Cancel</Button>
		<Button variant="danger" onclick={() => void confirmDelete()}>Delete layout</Button>
	{/snippet}
</Modal>

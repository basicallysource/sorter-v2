<script lang="ts">
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import {
		activateBsx,
		deactivateBsx,
		deleteBsx,
		fetchBsxLibrary,
		uploadBsx,
		type BsxFile
	} from '$lib/bsx/api';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Upload from '@lucide/svelte/icons/upload';
	import { onMount } from 'svelte';

	let { baseUrl }: { baseUrl: string } = $props();

	let files = $state<BsxFile[]>([]);
	let activeFilename = $state<string | null>(null);
	let loading = $state(true);
	let uploading = $state(false);
	let busyFilename = $state<string | null>(null);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let fileInput: HTMLInputElement | null = $state(null);

	async function load() {
		loading = true;
		try {
			const lib = await fetchBsxLibrary(baseUrl);
			files = lib.files;
			activeFilename = lib.active_filename;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load inventories';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function handleUpload(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		uploading = true;
		error = null;
		success = null;
		try {
			const name = file.name.replace(/\.bsx$/i, '');
			const entry = await uploadBsx(baseUrl, file, name);
			success = `Uploaded ${entry.name} (${entry.num_parts ?? 0} parts).`;
			await load();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to upload inventory';
		} finally {
			uploading = false;
		}
	}

	async function setActive(file: BsxFile) {
		busyFilename = file.filename;
		error = null;
		success = null;
		try {
			const lib = file.is_active ? await deactivateBsx(baseUrl) : await activateBsx(baseUrl, file.filename);
			files = lib.files;
			activeFilename = lib.active_filename;
			success = file.is_active ? `Deactivated ${file.name}.` : `${file.name} is now the active inventory.`;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to change active inventory';
		} finally {
			busyFilename = null;
		}
	}

	async function remove(file: BsxFile) {
		busyFilename = file.filename;
		error = null;
		success = null;
		try {
			const lib = await deleteBsx(baseUrl, file.filename);
			files = lib.files;
			activeFilename = lib.active_filename;
			success = `Deleted ${file.name}.`;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete inventory';
		} finally {
			busyFilename = null;
		}
	}

	function fmtDate(iso: string | null): string {
		if (!iso) return '—';
		const d = new Date(iso);
		return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
	}
</script>

<Panel
	title="BrickLink inventories (.bsx)"
	description="A store's on-hand inventory. One can be active; a profile with inventory routing sends pieces not in the active inventory to the not-in-inventory bin."
	flush
>
	{#snippet footer()}
		<Button icon={Upload} loading={uploading} onclick={() => fileInput?.click()}>Upload .bsx</Button>
	{/snippet}
	<input bind:this={fileInput} type="file" accept=".bsx" class="hidden" onchange={handleUpload} />

	{#if error || success}
		<div class="flex flex-col gap-2 px-(--pad-panel) pb-3">
			{#if error}<Alert tone="danger">{error}</Alert>{/if}
			{#if success}<Alert tone="success">{success}</Alert>{/if}
		</div>
	{/if}

	{#if loading}
		<p class="flex items-center gap-2 px-(--pad-panel) pb-4 text-sm text-ink-muted">
			<Spinner size={16} />
			Loading the inventories
		</p>
	{:else if files.length === 0}
		<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">No inventories uploaded yet.</p>
	{:else}
		<ul class="divide-y divide-line">
			{#each files as file (file.filename)}
				<li class="flex items-center justify-between gap-3 px-(--pad-panel) py-3">
					<div class="min-w-0">
						<div class="flex flex-wrap items-center gap-2">
							<span class="truncate text-sm font-medium text-ink">{file.name}</span>
							{#if file.is_active}<Badge tone="success" dot>Active</Badge>{/if}
							{#if file.error}<Badge tone="danger">Error</Badge>{/if}
						</div>
						<div class="mt-0.5 text-sm text-ink-muted">
							{file.num_parts ?? 0} parts · {file.num_unique_items ?? 0} items · uploaded {fmtDate(
								file.uploaded_at
							)}
						</div>
					</div>
					<div class="flex shrink-0 items-center gap-1">
						<Button
							variant={file.is_active ? 'secondary' : 'primary'}
							size="sm"
							loading={busyFilename === file.filename}
							disabled={!!file.error}
							onclick={() => setActive(file)}
						>
							{file.is_active ? 'Deactivate' : 'Set active'}
						</Button>
						<Button
							variant="ghost"
							size="sm"
							icon={Trash2}
							label="Delete {file.name}"
							disabled={busyFilename === file.filename}
							onclick={() => remove(file)}
						/>
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</Panel>

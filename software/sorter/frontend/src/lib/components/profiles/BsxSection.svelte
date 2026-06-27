<script lang="ts">
	import { Alert, Button } from '$lib/components/primitives';
	import {
		activateBsx,
		deactivateBsx,
		deleteBsx,
		fetchBsxLibrary,
		uploadBsx,
		type BsxFile
	} from '$lib/bsx/api';
	import { Trash2, Upload } from 'lucide-svelte';
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

<section class="flex flex-col gap-3">
	<div class="flex items-center justify-between gap-3">
		<div>
			<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">
				BrickLink inventories (.bsx)
			</h2>
			<p class="mt-1 text-sm text-text-muted">
				A store's on-hand inventory. One can be active; a profile with inventory routing sends
				pieces <em>not</em> in the active inventory to the not-in-inventory bin.
			</p>
		</div>
		<Button variant="secondary" size="sm" loading={uploading} onclick={() => fileInput?.click()}>
			<Upload class="h-4 w-4" />
			Upload .bsx
		</Button>
		<input
			bind:this={fileInput}
			type="file"
			accept=".bsx"
			class="hidden"
			onchange={handleUpload}
		/>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}
	{#if success}
		<Alert variant="success">{success}</Alert>
	{/if}

	{#if loading}
		<p class="text-sm text-text-muted">Loading…</p>
	{:else if files.length === 0}
		<p class="text-sm text-text-muted">No inventories uploaded yet.</p>
	{:else}
		<div class="flex flex-col divide-y divide-border border border-border">
			{#each files as file (file.filename)}
				<div class="flex items-center justify-between gap-3 bg-surface px-3 py-2">
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="truncate text-sm font-semibold text-text">{file.name}</span>
							{#if file.is_active}
								<span
									class="inline-flex items-center border border-success/60 bg-success/[0.12] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-success"
								>
									Active
								</span>
							{/if}
							{#if file.error}
								<span
									class="inline-flex items-center border border-danger/60 bg-danger/[0.12] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-danger"
								>
									Error
								</span>
							{/if}
						</div>
						<div class="mt-0.5 text-sm text-text-muted">
							{file.num_parts ?? 0} parts · {file.num_unique_items ?? 0} items · uploaded {fmtDate(
								file.uploaded_at
							)}
						</div>
					</div>
					<div class="flex shrink-0 items-center gap-2">
						<Button
							variant={file.is_active ? 'ghost' : 'primary'}
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
							loading={busyFilename === file.filename}
							onclick={() => remove(file)}
						>
							<Trash2 class="h-4 w-4" />
						</Button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</section>

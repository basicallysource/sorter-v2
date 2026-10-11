<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Trash2 from '@lucide/svelte/icons/trash';
	import Button from '$lib/components/ui/Button.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';

	const machine = getMachineContext();

	type StorageInfo = {
		stored: number;
		stored_bytes: number;
		not_on_every_hive: number;
		cap_bytes: number;
		disk_free_bytes: number | null;
		min_free_bytes: number;
		dropped_queue_full: number;
		skipped_low_disk: number;
	};

	let info = $state<StorageInfo | null>(null);
	let loading = $state(true);
	let errorMsg = $state<string | null>(null);
	let resultMsg = $state<string | null>(null);
	let purging = $state(false);
	let confirmPurge = $state(false);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB'];
		const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
	}

	async function loadStorage() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/samples/storage`);
			if (!res.ok) throw new Error(await res.text());
			info = await res.json();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load sample storage info';
		} finally {
			loading = false;
		}
	}

	async function purgeAll() {
		purging = true;
		errorMsg = null;
		resultMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/samples/storage`, {
				method: 'DELETE'
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			resultMsg = data.message ?? null;
			confirmPurge = false;
			await loadStorage();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to delete samples';
		} finally {
			purging = false;
		}
	}

	onMount(() => {
		loadStorage();
	});
</script>

{#if loading}
	<div class="flex items-center gap-2 px-(--pad-panel) py-4 text-sm text-ink-muted">
		<Spinner size={14} /> Loading the sample storage
	</div>
{:else if info}
	<div class="grid grid-cols-2 gap-px bg-line sm:grid-cols-4">
		<div class="bg-surface"><Stat label="Samples" value={info.stored.toLocaleString()} /></div>
		<div class="bg-surface">
			<Stat
				label="Size"
				value={formatBytes(info.stored_bytes)}
				hint="Of {formatBytes(info.cap_bytes)}"
			/>
		</div>
		<div class="bg-surface">
			<Stat label="Not on every Hive" value={info.not_on_every_hive.toLocaleString()} />
		</div>
		<div class="bg-surface">
			<Stat
				label="Disk free"
				value={info.disk_free_bytes === null ? 'Unknown' : formatBytes(info.disk_free_bytes)}
				tone={info.disk_free_bytes !== null && info.disk_free_bytes < info.min_free_bytes
					? 'warning'
					: undefined}
				hint="Needs {formatBytes(info.min_free_bytes)} free"
			/>
		</div>
	</div>

	{#if info.dropped_queue_full > 0 || info.skipped_low_disk > 0}
		<div class="flex flex-col gap-1 border-t border-line px-(--pad-panel) py-3 text-sm text-warning-ink">
			{#if info.dropped_queue_full > 0}
				<p>
					<span class="num font-medium">{info.dropped_queue_full.toLocaleString()}</span> frames dropped
					since startup because saving could not keep up.
				</p>
			{/if}
			{#if info.skipped_low_disk > 0}
				<p>
					<span class="num font-medium">{info.skipped_low_disk.toLocaleString()}</span> frames skipped
					since startup because the disk was low on space.
				</p>
			{/if}
		</div>
	{/if}

	{#if info.stored > 0}
		<div class="flex flex-wrap items-center justify-end gap-3 border-t border-line px-(--pad-panel) py-3">
			{#if confirmPurge}
				<span class="text-sm text-danger-ink">Delete every sample on this machine?</span>
				<Button variant="ghost" size="sm" onclick={() => (confirmPurge = false)}>Cancel</Button>
				<Button variant="danger" size="sm" loading={purging} onclick={purgeAll}>Delete all</Button>
			{:else}
				<Button variant="danger" size="sm" icon={Trash2} onclick={() => (confirmPurge = true)}>
					Delete all samples on this machine
				</Button>
			{/if}
		</div>
	{/if}
{/if}

{#if resultMsg}
	<div class="px-(--pad-panel) py-(--pad-panel)">
		<Alert tone="success">{resultMsg}</Alert>
	</div>
{/if}
{#if errorMsg}
	<div class="px-(--pad-panel) py-(--pad-panel)">
		<Alert tone="danger">{errorMsg}</Alert>
	</div>
{/if}

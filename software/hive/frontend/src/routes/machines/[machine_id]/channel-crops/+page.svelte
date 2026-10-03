<script lang="ts">
	import { page } from '$app/state';
	import { api, type MachineChannelCropInfo } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Crop from '@lucide/svelte/icons/crop';

	const PAGE_SIZE = 120;

	const machineId = $derived(page.params.machine_id ?? '');

	let machineName = $state<string>('');
	let crops = $state<MachineChannelCropInfo[]>([]);
	let total = $state(0);
	let nextCursor = $state<number | null>(null);
	let loading = $state(true);
	let loadingMore = $state(false);
	let error = $state<string | null>(null);
	let sentinel = $state<HTMLDivElement | null>(null);

	// Filters. null = all.
	let channel = $state<number | null>(null);
	let zoneCode = $state<number | null>(null);

	$effect(() => {
		// Re-run the initial load whenever route id or a filter changes.
		void machineId;
		void channel;
		void zoneCode;
		void loadInitial();
	});

	$effect(() => {
		const el = sentinel;
		if (!el) return;
		const observer = new IntersectionObserver((entries) => {
			if (entries.some((e) => e.isIntersecting)) void loadMore();
		});
		observer.observe(el);
		return () => observer.disconnect();
	});

	async function loadInitial() {
		if (!machineId) return;
		loading = true;
		error = null;
		crops = [];
		nextCursor = null;
		try {
			const res = await api.getMachineChannelCrops(machineId, {
				limit: PAGE_SIZE,
				channel,
				zoneCode
			});
			machineName = res.machine.name;
			crops = res.items;
			total = res.total;
			nextCursor = res.next_cursor;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load channel crops');
		} finally {
			loading = false;
		}
	}

	async function loadMore() {
		if (loadingMore || loading || nextCursor == null) return;
		loadingMore = true;
		try {
			const res = await api.getMachineChannelCrops(machineId, {
				limit: PAGE_SIZE,
				cursor: nextCursor,
				channel,
				zoneCode
			});
			crops = [...crops, ...res.items];
			nextCursor = res.next_cursor;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load more crops');
		} finally {
			loadingMore = false;
		}
	}

	function errMsg(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: fallback;
	}

	const ZONE_LABELS: Record<number, string> = { 0: 'mid', 1: 'drop', 2: 'exit', 3: 'precise' };

	function zoneLabel(z: number | null): string {
		return z == null ? '-' : (ZONE_LABELS[z] ?? String(z));
	}

	// The dot's color is the zone the piece's center sat in. Near the exit is
	// where matching the same piece matters most, so exit and precise stand out.
	function zoneDot(z: number | null): string {
		switch (z) {
			case 3:
				return 'bg-success';
			case 2:
				return 'bg-primary';
			case 1:
				return 'bg-info';
			default:
				return 'bg-ink-faint';
		}
	}

	function deg(d: number | null): string {
		return d == null ? '-' : `${d.toFixed(1)}°`;
	}

	function when(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleTimeString();
	}

</script>

<svelte:head>
	<title>{machineName ? `${machineName} channel crops` : 'Channel crops'} - Hive</title>
</svelte:head>

<div>
	<Button href={`/machines/${machineId}`} size="sm" variant="ghost" icon={ArrowLeft}>Machine overview</Button>
</div>

<PageHeader
	title={machineName || 'Machine'}
	description="Unlabeled crops of pieces on the second and third channels, tagged with how far the piece was from the exit, for matching the same piece later."
>
	{#snippet actions()}
		{#if !loading}
			<span class="num text-sm text-ink-muted"
				>{crops.length.toLocaleString()} of {total.toLocaleString()} loaded</span
			>
		{/if}
	{/snippet}
</PageHeader>

<div class="flex flex-wrap items-center gap-2">
	<SegmentedControl
		label="Channel"
		size="sm"
		value={channel === null ? 'all' : String(channel)}
		onchange={(v: string) => (channel = v === 'all' ? null : Number(v))}
		options={[
			{ value: 'all', label: 'All channels' },
			{ value: '2', label: 'C2' },
			{ value: '3', label: 'C3' }
		]}
	/>
	<SegmentedControl
		label="Zone"
		size="sm"
		value={zoneCode === null ? 'all' : String(zoneCode)}
		onchange={(v: string) => (zoneCode = v === 'all' ? null : Number(v))}
		options={[
			{ value: 'all', label: 'All zones' },
			{ value: '2', label: 'Exit' },
			{ value: '3', label: 'Precise' },
			{ value: '1', label: 'Drop' },
			{ value: '0', label: 'Mid' }
		]}
	/>
</div>

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}

{#if loading}
	<div class="flex justify-center py-12"><Spinner size={32} /></div>
{:else if crops.length === 0}
	<Panel>
		<EmptyState icon={Crop} title="No channel crops yet">No channel crops have synced from this machine yet.</EmptyState>
	</Panel>
{:else}
	<Panel>
		<div class="grid grid-cols-[repeat(auto-fill,minmax(6rem,1fr))] gap-3">
			{#each crops as crop (crop.local_id)}
				<figure class="flex flex-col gap-1.5">
					{#if crop.available}
						<img
							src={api.machineChannelCropImageUrl(machineId, crop.local_id)}
							alt={`Crop ${crop.local_id}`}
							loading="lazy"
							title={`C${crop.channel}, ${zoneLabel(crop.zone_code)}, ${deg(
								crop.com_forward_to_exit_deg
							)} to the exit, track ${crop.track_id ?? '-'}, ${when(crop.ts)}`}
							class="h-20 w-full rounded-control object-contain"
						/>
					{:else}
						<div
							class="flex h-20 w-full items-center justify-center rounded-control bg-well text-center text-xs text-ink-muted"
							title="Removed before it synced"
						>
							Removed
						</div>
					{/if}
					<figcaption class="text-xs leading-tight text-ink-muted">
						<span class="flex items-center gap-1.5 text-ink">
							<span class="size-1.5 shrink-0 rounded-full {zoneDot(crop.zone_code)}" aria-hidden="true"></span>
							C{crop.channel}, {zoneLabel(crop.zone_code)}
						</span>
						<span class="num">{deg(crop.com_forward_to_exit_deg)}</span>
					</figcaption>
				</figure>
			{/each}
		</div>
	</Panel>

	<div bind:this={sentinel} class="h-px"></div>

	<div class="flex justify-center py-6">
		{#if loadingMore}
			<Spinner size={24} />
		{:else if nextCursor != null}
			<Button size="sm" onclick={loadMore}>Load more</Button>
		{:else}
			<span class="text-sm text-ink-muted">End of the list, {total.toLocaleString()} crops.</span>
		{/if}
	</div>
{/if}

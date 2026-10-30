<script lang="ts">
	import { page } from '$app/state';
	import Cloud from '@lucide/svelte/icons/cloud';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import HourlyChart, {
		type HourlySeries,
		type TipRow
	} from '$lib/components/data/HourlyChart.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import {
		getSharing,
		getSharingStats,
		sharedWith,
		type KindSeries,
		type Sharing,
		type SharingStats,
		type StatsKind
	} from '$lib/sharing/api';
	import { formatAgo, formatBytes, formatCount, formatWait } from '$lib/sharing/format';

	const machine = getMachineContext();

	const POLL_MS = 30_000;
	const RANGES: { value: '24' | '168'; label: string }[] = [
		{ value: '24', label: '24 hours' },
		{ value: '168', label: '7 days' }
	];

	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());

	let range = $state<'24' | '168'>('24');
	// The Hive being looked at: ?hive=<id>, else the first.
	let chosen = $state<string | null>(null);
	let stats = $state<SharingStats | null>(null);
	let sharing = $state<Sharing | null>(null);
	let error = $state<string | null>(null);
	// A newer answer is on its way; the page keeps the last one in the meantime.
	let refreshing = $state(false);

	const target = $derived(
		stats?.targets.find((t) => t.id === chosen) ?? stats?.targets[0] ?? null
	);
	const kinds = $derived(stats?.kinds ?? []);
	const hours = $derived(stats?.hour_starts ?? []);

	function message(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	$effect(() => {
		const wanted = page.url.searchParams.get('hive');
		if (wanted) chosen = wanted;
	});

	async function load(from: string, shown: '24' | '168') {
		refreshing = true;
		try {
			const next = await getSharingStats(from, shown === '24' ? 24 : 168);
			if (from !== base || shown !== range) return;
			stats = next;
			error = null;
		} catch (e) {
			if (from === base && shown === range) {
				error = `Couldn't load the upload numbers: ${message(e)}`;
			}
		} finally {
			refreshing = false;
		}
	}

	// Every 30 seconds while the page is open, and at once when the range changes.
	$effect(() => {
		const from = base;
		const shown = range;
		void load(from, shown);
		const timer = setInterval(() => void load(from, shown), POLL_MS);
		return () => clearInterval(timer);
	});

	// Which streams are off for this Hive, to explain a kind with nothing in it.
	$effect(() => {
		const from = base;
		getSharing(from)
			.then((next) => {
				if (from === base) sharing = next;
			})
			.catch(() => {});
	});

	function seriesOf(kind: StatsKind): KindSeries | undefined {
		return target?.series[kind.key];
	}

	// A kind keeps its color wherever it is shown: the large ones are shades of
	// the primary in the order the machine lists them, the small ones are grays.
	const GRAYS = ['var(--ink-muted)', 'var(--ink-faint)', 'var(--line-strong)'];

	function shade(kind: StatsKind): { color: string; opacity: number } {
		const same = kinds.filter((k) => k.size === kind.size);
		const i = same.findIndex((k) => k.key === kind.key);
		if (kind.size === 'small') return { color: GRAYS[Math.min(i, GRAYS.length - 1)], opacity: 1 };
		return { color: 'var(--primary-ink)', opacity: same.length > 1 ? 1 - (i / (same.length - 1)) * 0.55 : 1 };
	}

	function sumAt(pick: (s: KindSeries) => number[] | undefined, i: number): number {
		return kinds.reduce((sum, kind) => {
			const s = seriesOf(kind);
			return sum + ((s && pick(s)?.[i]) || 0);
		}, 0);
	}

	function sum(values: number[] | undefined): number {
		return (values ?? []).reduce((a, b) => a + b, 0);
	}

	const sentBytes = $derived(kinds.map((kind) => sum(seriesOf(kind)?.sent_bytes)));
	const sentItems = $derived(kinds.map((kind) => sum(seriesOf(kind)?.sent)));
	const droppedItems = $derived(kinds.map((kind) => sum(seriesOf(kind)?.dropped)));
	const droppedBytes = $derived(kinds.map((kind) => sum(seriesOf(kind)?.dropped_bytes)));
	const total = (values: number[]) => values.reduce((a, b) => a + b, 0);
	const waitingNow = $derived(total(kinds.map((kind) => target?.waiting_now[kind.key] ?? 0)));
	const heldBack = $derived(sum(target?.budget_wait_s));

	const bytesSeries = $derived<HourlySeries[]>(
		kinds.map((kind) => ({
			key: kind.key,
			label: kind.label,
			values: seriesOf(kind)?.sent_bytes ?? [],
			...shade(kind)
		}))
	);

	// The backlog at the end of each hour, all kinds together; unknown where no
	// kind knew it.
	const backlog = $derived<HourlySeries[]>([
		{
			key: 'waiting',
			label: 'Waiting',
			color: 'var(--primary-ink)',
			values: hours.map((_, i) => {
				let known = false;
				let count = 0;
				for (const kind of kinds) {
					const v = seriesOf(kind)?.waiting[i];
					if (v != null) {
						known = true;
						count += v;
					}
				}
				return known ? count : null;
			})
		}
	]);

	const droppedHours = $derived(hours.map((_, i) => sumAt((s) => s.dropped, i) > 0));

	function sentNotes(i: number): TipRow[] {
		const items = sumAt((s) => s.sent, i);
		return items > 0 ? [{ label: 'Items sent', value: formatCount(items) }] : [];
	}

	function backlogNotes(i: number): TipRow[] {
		const dropped = sumAt((s) => s.dropped, i);
		const waited = target?.budget_wait_s[i] ?? 0;
		return [
			...(dropped > 0 ? [{ label: 'Not uploaded', value: formatCount(dropped) }] : []),
			...(waited >= 1 ? [{ label: 'Held back by the budget', value: formatWait(waited) }] : [])
		];
	}

	// The budget is set in megabytes of 1,000,000 bytes, so it reads as set.
	const budgetText = $derived.by(() => {
		const budget = target?.upload_budget;
		if (!budget) return undefined;
		const megabytes = Math.round(budget.bytes_per_minute / 1e5) / 10;
		return `${megabytes} MB and ${formatCount(budget.files_per_minute)} files a minute`;
	});

	function streamOff(kind: StatsKind): boolean {
		const stream = sharing?.streams.find((s) => s.key === kind.stream);
		return Boolean(sharing && stream && target && !sharedWith(sharing, stream, target.id));
	}
</script>

<svelte:head><title>Sorter - Uploads</title></svelte:head>

<PageHeader
	title="Uploads"
	description="What this sorter has sent to a Hive, what is waiting to go, and what will never be sent."
>
	{#snippet actions()}
		{#if stats && stats.targets.length > 0}
			<Select
				label="Hive"
				value={target?.id}
				options={stats.targets.map((t) => ({
					value: t.id,
					label: t.name,
					hint: t.reachable ? undefined : 'Unreachable'
				}))}
				onchange={(id) => (chosen = id)}
				class="w-48"
			/>
			<SegmentedControl
				label="Time shown"
				options={RANGES}
				value={range}
				onchange={(value) => (range = value)}
			/>
		{/if}
	{/snippet}
</PageHeader>

{#if error && !stats}
	<Alert tone="danger">{error}</Alert>
{:else if !stats}
	<Panel>
		<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading</p>
	</Panel>
{:else if !target}
	<EmptyState icon={Cloud} title="No Hive is connected">
		Connect this sorter to a Hive and its uploads are counted here.
		{#snippet action()}
			<Button href="/settings/hive">Go to Hive settings</Button>
		{/snippet}
	</EmptyState>
{:else}
	<div
		class="flex flex-col gap-(--gap-panels) transition-opacity {refreshing ? 'opacity-60' : ''}"
		aria-busy={refreshing}
	>
		{#if error}<Alert tone="warning">{error}</Alert>{/if}
		{#if !target.reachable}
			<Alert tone="warning" title="{target.name} can't be reached">
				Nothing is being sent to it. What is waiting stays on this machine until it answers.
			</Alert>
		{/if}

		<Panel flush>
			<div class="grid grid-cols-2 gap-px bg-line lg:grid-cols-4">
				<div class="bg-surface">
					<Stat
						label="Uploaded"
						value={formatBytes(total(sentBytes))}
						hint="{formatCount(total(sentItems))} items"
					/>
				</div>
				<div class="bg-surface">
					<Stat label="Waiting now" value={formatCount(waitingNow)} hint="items to upload" />
				</div>
				<div class="bg-surface">
					<Stat
						label="Not uploaded"
						value={formatCount(total(droppedItems))}
						hint={total(droppedItems) > 0 ? formatBytes(total(droppedBytes)) : 'None'}
						tone={total(droppedItems) > 0 ? 'warning' : undefined}
					/>
				</div>
				<div class="bg-surface">
					<Stat label="Held back" value={formatWait(heldBack)} hint="By the upload budget" />
				</div>
			</div>
			<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
				{#if budgetText}Uploads wait for room under a limit of {budgetText}.{/if}
				Not uploaded is what was skipped to keep up, or deleted here before it was sent.
			</p>
		</Panel>

		<Panel
			title="Uploaded"
			description="Bytes sent to {target.name} each hour, by kind. Point at an hour for its numbers."
		>
			<HourlyChart
				label="Bytes uploaded to {target.name} each hour"
				{hours}
				series={bytesSeries}
				format={formatBytes}
				bytes
				totalLabel="uploaded"
				notes={sentNotes}
				empty="Nothing was uploaded in this time."
			/>
		</Panel>

		<Panel
			title="Waiting to upload"
			description="Items waiting at the end of each hour. A mark along the bottom is an hour when some were skipped or deleted before they could be sent."
		>
			<HourlyChart
				label="Items waiting to upload to {target.name}"
				form="area"
				{hours}
				series={backlog}
				format={formatCount}
				totalLabel="waiting"
				flagged={droppedHours}
				flagLabel="Hours with items not uploaded"
				notes={backlogNotes}
				empty="Nothing was waiting in this time."
			/>
		</Panel>

		<Panel
			title="By kind"
			description="Counted over the time shown."
			flush
		>
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr>
							<th>Kind</th>
							<th>Last upload</th>
							<th class="num">Uploaded</th>
							<th class="num">Size</th>
							<th class="num">Waiting now</th>
							<th class="num">Not uploaded</th>
						</tr>
					</thead>
					<tbody>
						{#each kinds as kind, k (kind.key)}
							{@const last = target.last_sent_at[kind.key]}
							<tr>
								<td>
									<span class="flex items-center gap-2 whitespace-nowrap">
										{kind.label}
										{#if streamOff(kind)}<Badge>Off for this Hive</Badge>{/if}
									</span>
								</td>
								<td class="whitespace-nowrap text-ink-muted">
									{last == null ? 'Never' : formatAgo(stats.now - last)}
								</td>
								<td class="num">{formatCount(sentItems[k])}</td>
								<td class="num whitespace-nowrap">{formatBytes(sentBytes[k])}</td>
								<td class="num">{formatCount(target.waiting_now[kind.key] ?? 0)}</td>
								<td class="num {droppedItems[k] > 0 ? 'text-warning-ink' : ''}">
									{formatCount(droppedItems[k])}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Panel>
	</div>
{/if}

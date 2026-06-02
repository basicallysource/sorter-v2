<script lang="ts">
	import { onMount } from 'svelte';
	import { RefreshCw, ChevronLeft, ChevronRight } from 'lucide-svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { getMachineContext } from '$lib/machines/context';

	type Overview = {
		total_runs: number;
		total_pieces: number;
		classified_pieces: number;
		distributed_pieces: number;
		unique_parts: number;
		unique_colors: number;
		first_seen: number | null;
		last_seen: number | null;
	};

	type PieceItem = {
		uuid: string;
		run_id: string;
		seen_at: number | null;
		classification_status: string | null;
		part_id: string | null;
		part_name: string | null;
		color_id: string | null;
		color_name: string | null;
		category_id: string | null;
		confidence: number | null;
		destination_bin: number[] | null;
	};

	type LifetimeDay = {
		day: string;
		seconds_powered: number;
		seconds_sorted: number;
		pieces_seen: number;
		pieces_classified: number;
		pieces_distributed: number;
	};

	type Lifetime = {
		seconds_sorted: number;
		seconds_powered: number;
		pieces_seen: number;
		pieces_classified: number;
		pieces_distributed: number;
		overall_ppm: number;
		best_hour_ppm: number;
		active_days: number;
		first_hour: number | null;
		last_hour: number | null;
		daily: LifetimeDay[];
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	const PAGE_SIZE = 50;

	let overview = $state<Overview | null>(null);
	let lifetime = $state<Lifetime | null>(null);
	let pieces = $state<PieceItem[]>([]);
	let total = $state(0);
	let offset = $state(0);
	let loading = $state(false);

	let pageNum = $derived(Math.floor(offset / PAGE_SIZE) + 1);
	let pageCount = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));

	async function loadOverview() {
		try {
			const res = await fetch(`${effectiveBase()}/api/records/overview`);
			if (!res.ok) return;
			overview = await res.json();
		} catch {
			// ignore
		}
	}

	async function loadLifetime() {
		try {
			const res = await fetch(`${effectiveBase()}/api/records/lifetime`);
			if (!res.ok) return;
			lifetime = await res.json();
		} catch {
			// ignore
		}
	}

	async function loadPieces() {
		loading = true;
		try {
			const res = await fetch(
				`${effectiveBase()}/api/records/pieces?offset=${offset}&limit=${PAGE_SIZE}`
			);
			if (!res.ok) return;
			const json = await res.json();
			pieces = Array.isArray(json?.pieces) ? json.pieces : [];
			total = typeof json?.total === 'number' ? json.total : 0;
		} catch {
			// ignore
		} finally {
			loading = false;
		}
	}

	function refresh() {
		void loadOverview();
		void loadLifetime();
		void loadPieces();
	}

	function prevPage() {
		if (offset <= 0) return;
		offset = Math.max(0, offset - PAGE_SIZE);
		void loadPieces();
	}

	function nextPage() {
		if (offset + PAGE_SIZE >= total) return;
		offset = offset + PAGE_SIZE;
		void loadPieces();
	}

	function formatTimestamp(ts: number | null): string {
		if (ts == null) return '—';
		const d = new Date(ts * 1000);
		return d.toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatDate(ts: number | null): string {
		if (ts == null) return '—';
		return new Date(ts * 1000).toLocaleDateString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
	}

	function formatStatus(status: string | null): string {
		if (!status) return 'unknown';
		return status.replace(/_/g, ' ');
	}

	function statusClass(status: string | null): string {
		if (status === 'classified') return 'text-success';
		if (status === 'not_found' || status === 'unknown') return 'text-warning';
		if (status === 'multi_drop_fail') return 'text-danger';
		return 'text-text-muted';
	}

	function formatBin(bin: number[] | null): string {
		if (!bin || bin.length === 0) return '—';
		return bin.join(', ');
	}

	function formatConfidence(c: number | null): string {
		if (c == null) return '—';
		return `${(c * 100).toFixed(0)}%`;
	}

	function formatDuration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '0h 0m';
		const total_min = Math.floor(seconds / 60);
		const days = Math.floor(total_min / 1440);
		const hours = Math.floor((total_min % 1440) / 60);
		const mins = total_min % 60;
		if (days > 0) return `${days}d ${hours}h`;
		return `${hours}h ${mins}m`;
	}

	function formatHours(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '0';
		return (seconds / 3600).toLocaleString(undefined, { maximumFractionDigits: 1 });
	}

	function formatPpm(ppm: number | null | undefined): string {
		if (!ppm || ppm <= 0) return '—';
		return ppm.toLocaleString(undefined, { maximumFractionDigits: 1 });
	}

	let utilizationPct = $derived(
		lifetime && lifetime.seconds_powered > 0
			? (lifetime.seconds_sorted / lifetime.seconds_powered) * 100
			: 0
	);

	function formatDayLabel(day: string): string {
		const d = new Date(`${day}T00:00:00`);
		if (Number.isNaN(d.getTime())) return day;
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	onMount(() => {
		refresh();
	});
</script>

<svelte:head>
	<title>Records · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="flex flex-col gap-4 p-4 sm:p-6">
		<header class="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
			<div>
				<h2 class="text-xl font-bold text-text">Records</h2>
				<p class="mt-1 text-sm text-text-muted">
					Sorting history for this machine — every piece seen across all saved runs.
				</p>
			</div>
			<button
				type="button"
				onclick={refresh}
				disabled={loading}
				aria-label="Reload"
				title="Reload records"
				class="border border-border bg-surface p-1.5 text-text-muted hover:text-text disabled:opacity-50"
			>
				<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
			</button>
		</header>

		{#snippet statCard(label: string, value: string)}
			<div class="border border-border bg-surface px-4 py-3">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">{label}</div>
				<div class="mt-1 text-2xl font-bold text-text">{value}</div>
			</div>
		{/snippet}
		{#snippet statCardSub(label: string, value: string, sub: string)}
			<div class="border border-border bg-surface px-4 py-3">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">{label}</div>
				<div class="mt-1 text-2xl font-bold text-text">{value}</div>
				<div class="mt-0.5 text-sm text-text-muted">{sub}</div>
			</div>
		{/snippet}

		<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">Lifetime</h3>
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			{@render statCardSub(
				'Hours sorted',
				lifetime ? formatHours(lifetime.seconds_sorted) : '—',
				lifetime ? formatDuration(lifetime.seconds_sorted) + ' active' : ''
			)}
			{@render statCardSub(
				'Hours powered',
				lifetime ? formatHours(lifetime.seconds_powered) : '—',
				lifetime ? formatDuration(lifetime.seconds_powered) + ' on' : ''
			)}
			{@render statCard('Utilization', lifetime ? `${utilizationPct.toFixed(0)}%` : '—')}
			{@render statCard('Active days', lifetime ? lifetime.active_days.toLocaleString() : '—')}
			{@render statCard(
				'Pieces sorted',
				lifetime ? lifetime.pieces_distributed.toLocaleString() : '—'
			)}
			{@render statCardSub(
				'Throughput',
				lifetime ? formatPpm(lifetime.overall_ppm) : '—',
				'avg pieces/min'
			)}
			{@render statCardSub(
				'Best hour',
				lifetime ? formatPpm(lifetime.best_hour_ppm) : '—',
				'peak pieces/min'
			)}
			{@render statCard(
				'Classified',
				lifetime ? lifetime.pieces_classified.toLocaleString() : '—'
			)}
		</div>

		{#if lifetime && lifetime.daily.length > 0}
			<div class="overflow-x-auto border border-border">
				<table class="w-full border-collapse text-sm">
					<thead>
						<tr class="border-b border-border bg-surface text-left text-text-muted">
							<th class="px-3 py-2 font-semibold">Day</th>
							<th class="px-3 py-2 font-semibold">Powered</th>
							<th class="px-3 py-2 font-semibold">Sorted</th>
							<th class="px-3 py-2 font-semibold">Pieces</th>
							<th class="px-3 py-2 font-semibold">Classified</th>
							<th class="px-3 py-2 font-semibold">PPM</th>
						</tr>
					</thead>
					<tbody>
						{#each lifetime.daily as d (d.day)}
							<tr class="border-b border-border last:border-b-0 hover:bg-surface">
								<td class="px-3 py-2 text-text">{formatDayLabel(d.day)}</td>
								<td class="px-3 py-2 text-text-muted">{formatDuration(d.seconds_powered)}</td>
								<td class="px-3 py-2 text-text">{formatDuration(d.seconds_sorted)}</td>
								<td class="px-3 py-2 text-text">{d.pieces_distributed.toLocaleString()}</td>
								<td class="px-3 py-2 text-text-muted">{d.pieces_classified.toLocaleString()}</td>
								<td class="px-3 py-2 text-text">
									{formatPpm(d.seconds_sorted > 0 ? (d.pieces_distributed * 60) / d.seconds_sorted : 0)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">History</h3>
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			{@render statCard('Pieces seen', overview ? overview.total_pieces.toLocaleString() : '—')}
			{@render statCard(
				'Classified',
				overview ? overview.classified_pieces.toLocaleString() : '—'
			)}
			{@render statCard(
				'Distributed',
				overview ? overview.distributed_pieces.toLocaleString() : '—'
			)}
			{@render statCard('Runs', overview ? overview.total_runs.toLocaleString() : '—')}
			{@render statCard('Unique parts', overview ? overview.unique_parts.toLocaleString() : '—')}
			{@render statCard('Unique colors', overview ? overview.unique_colors.toLocaleString() : '—')}
			{@render statCard('First seen', overview ? formatDate(overview.first_seen) : '—')}
			{@render statCard('Last seen', overview ? formatDate(overview.last_seen) : '—')}
		</div>

		<div class="flex items-center justify-between gap-3">
			<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">
				Pieces
			</h3>
			<div class="flex items-center gap-3 text-sm text-text-muted">
				<span>
					{#if total > 0}
						{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
					{:else}
						0 records
					{/if}
				</span>
				<div class="flex border border-border">
					<button
						type="button"
						onclick={prevPage}
						disabled={offset <= 0 || loading}
						aria-label="Previous page"
						class="border-r border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronLeft size={14} />
					</button>
					<span class="px-3 py-1 text-text">{pageNum} / {pageCount}</span>
					<button
						type="button"
						onclick={nextPage}
						disabled={offset + PAGE_SIZE >= total || loading}
						aria-label="Next page"
						class="border-l border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronRight size={14} />
					</button>
				</div>
			</div>
		</div>

		<div class="overflow-x-auto border border-border">
			<table class="w-full border-collapse text-sm">
				<thead>
					<tr class="border-b border-border bg-surface text-left text-text-muted">
						<th class="px-3 py-2 font-semibold">Seen</th>
						<th class="px-3 py-2 font-semibold">Part</th>
						<th class="px-3 py-2 font-semibold">Color</th>
						<th class="px-3 py-2 font-semibold">Status</th>
						<th class="px-3 py-2 font-semibold">Confidence</th>
						<th class="px-3 py-2 font-semibold">Bin</th>
					</tr>
				</thead>
				<tbody>
					{#if pieces.length === 0}
						<tr>
							<td colspan="6" class="px-3 py-6 text-center text-text-muted">
								{loading ? 'Loading…' : 'No records yet.'}
							</td>
						</tr>
					{:else}
						{#each pieces as p (p.uuid)}
							<tr class="border-b border-border last:border-b-0 hover:bg-surface">
								<td class="px-3 py-2 text-text">{formatTimestamp(p.seen_at)}</td>
								<td class="px-3 py-2 text-text">
									{#if p.part_id}
										<span class="font-mono">{p.part_id}</span>{#if p.part_name}
											<span class="text-text-muted"> · {p.part_name}</span>{/if}
									{:else}
										—
									{/if}
								</td>
								<td class="px-3 py-2 text-text">{p.color_name ?? p.color_id ?? '—'}</td>
								<td class="px-3 py-2 {statusClass(p.classification_status)}">
									{formatStatus(p.classification_status)}
								</td>
								<td class="px-3 py-2 text-text">{formatConfidence(p.confidence)}</td>
								<td class="px-3 py-2 font-mono text-text">{formatBin(p.destination_bin)}</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
	</div>
</div>

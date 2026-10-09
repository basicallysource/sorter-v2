<script lang="ts">
	/*
		Where each piece's seconds go on the classification channel (C4): its own
		work (confirming the landing, photos, waiting for the piece ahead to be
		classified and the chute aimed, the turn), and its waits for the feeder,
		split by where C3's next piece was when C4 asked. From the machine's
		piece cycles (/runtime-stats/cycles), one row per piece. Cycles that
		overlap an incident are counted apart: they are stops, not the flow.
	*/
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { RUNTIME_SPANS, type RuntimeSpan } from '$lib/components/RuntimeStats.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';

	type Q = { n: number; median?: number; mean?: number; p90?: number; total?: number };
	type Case = Q & { key: string; label: string; share: number; c3_moving: number | null; chute: number | null };
	type Summary = {
		pieces: number;
		held: number;
		per_minute: number | null;
		multi_drop: number;
		c4: { confirm: Q; photos: Q; head_ready: Q; turn: Q; total: Q };
		wait: Q;
		cycle: Q;
		wait_cases: Case[];
		long_waits: { n: number; seconds: number; share: number };
	};
	type Wait = {
		id: number;
		asked_at: number;
		landed_at: number;
		c3_head_deg: number | null;
		c3_next_deg: number | null;
		c3_pieces: number | null;
		c2_pieces: number | null;
		c3_hidden: number | null;
		c3_moving_s: number | null;
		chute_s: number | null;
	};

	const ctx = getMachineContext();
	let span = $state<RuntimeSpan>('1h');
	let summary = $state<Summary | null>(null);
	let waits = $state<Wait[]>([]);

	function since(s: RuntimeSpan): number {
		const now = Date.now() / 1000;
		if (s === '10m') return now - 600;
		if (s === '1h') return now - 3600;
		const midnight = new Date();
		midnight.setHours(0, 0, 0, 0);
		return midnight.getTime() / 1000;
	}

	async function load() {
		const base = machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
		const from = since(span);
		try {
			const [s, w] = await Promise.all([
				fetch(`${base}/runtime-stats/cycles?since=${from}`),
				fetch(`${base}/runtime-stats/cycles/waits?since=${from}&min_s=4&limit=40`)
			]);
			if (s.ok) summary = await s.json();
			if (w.ok) waits = (await w.json()).waits ?? [];
		} catch {
			// The next poll tries again.
		}
	}

	$effect(() => {
		void span;
		void ctx.machine?.url;
		load();
		const id = setInterval(load, 10000);
		return () => clearInterval(id);
	});

	const secs = (v: number | undefined | null) => (v == null ? '—' : `${v.toFixed(1)} s`);
	const pct = (v: number | undefined | null) => (v == null ? '—' : `${Math.round(v * 100)}%`);
	const clock = (t: number) =>
		new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }).toLowerCase();
	function where(w: Wait): string {
		if (w.c3_head_deg == null) return 'No piece seen on C3';
		return `${Math.max(0, Math.round(w.c3_head_deg))}° from C3's edge`;
	}

	const phases = $derived(
		summary
			? [
					{ label: 'Landing confirmed', q: summary.c4.confirm },
					{ label: 'Photos', q: summary.c4.photos },
					{ label: 'Waiting for the piece ahead (classified, chute aimed)', q: summary.c4.head_ready },
					{ label: 'Turn (eject the piece ahead, stage this one)', q: summary.c4.turn },
					{ label: 'All of C4’s own work', q: summary.c4.total }
				]
			: []
	);
</script>

<svelte:head><title>Sorter - Cycle time</title></svelte:head>

<PageHeader
	title="Cycle time"
	description="Where each piece's seconds go on the classification channel: its own work, and its waits for the feeder."
>
	{#snippet actions()}
		<SegmentedControl bind:value={span} options={RUNTIME_SPANS} label="Time span" size="sm" />
	{/snippet}
</PageHeader>

<div class="flex flex-col gap-4">
	<Panel flush>
		<div class="grid grid-cols-2 gap-px bg-line md:grid-cols-4">
			<div class="bg-surface">
				<Stat
					label="Pieces a minute"
					value={summary?.per_minute != null ? summary.per_minute.toFixed(1) : '—'}
					hint={summary ? `${summary.pieces} pieces${summary.held ? `, ${summary.held} during stops` : ''}` : undefined}
				/>
			</div>
			<div class="bg-surface">
				<Stat label="Per piece, on average" value={secs(summary?.cycle.mean)} hint={`Median ${secs(summary?.cycle.median)}`} />
			</div>
			<div class="bg-surface">
				<Stat label="C4's own work" value={secs(summary?.c4.total.mean)} hint={`Median ${secs(summary?.c4.total.median)}`} />
			</div>
			<div class="bg-surface">
				<Stat
					label="Waiting for the feeder"
					value={secs(summary?.wait.mean)}
					hint={summary ? `Median ${secs(summary.wait.median)}, ${pct(summary.long_waits.share)} in waits over 4 s` : undefined}
				/>
			</div>
		</div>
	</Panel>

	<Panel title="C4's own work" description="From the moment a piece lands until C4 asks for the next one." flush>
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>Phase</th>
						<th class="num">Median</th>
						<th class="num">Average</th>
						<th class="num">Slowest 10%</th>
					</tr>
				</thead>
				<tbody>
					{#each phases as p (p.label)}
						<tr>
							<td>{p.label}</td>
							<td class="num">{secs(p.q.median)}</td>
							<td class="num">{secs(p.q.mean)}</td>
							<td class="num text-ink-muted">{secs(p.q.p90)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</Panel>

	<Panel
		title="Waiting for the feeder"
		description="Each wait, by where C3's next piece was when C4 asked. Moving is the share of the wait C3 (or the chute) was turning."
		flush
	>
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>When C4 asked</th>
						<th class="num">Asks</th>
						<th class="num">Median</th>
						<th class="num">Average</th>
						<th class="num">Seconds in all</th>
						<th class="num">C3 moving</th>
						<th class="num">Chute moving</th>
					</tr>
				</thead>
				<tbody>
					{#each summary?.wait_cases ?? [] as c (c.key)}
						<tr>
							<td>{c.label}</td>
							<td class="num">{c.n} <span class="text-ink-muted">({pct(c.share)})</span></td>
							<td class="num">{secs(c.median)}</td>
							<td class="num">{secs(c.mean)}</td>
							<td class="num">{c.total != null ? Math.round(c.total) : '—'}</td>
							<td class="num text-ink-muted">{pct(c.c3_moving)}</td>
							<td class="num text-ink-muted">{pct(c.chute)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</Panel>

	<Panel title="Longest waits" description="Waits over 4 s, longest first." flush>
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>When</th>
						<th class="num">Wait</th>
						<th>C3's next piece</th>
						<th class="num">On C3</th>
						<th class="num">On C2</th>
						<th class="num">C3 moving</th>
						<th class="num">Chute moving</th>
					</tr>
				</thead>
				<tbody>
					{#if waits.length === 0}
						<tr><td class="text-center text-ink-muted" colspan="7">No waits over 4 s.</td></tr>
					{:else}
						{#each waits as w (w.id)}
							{@const wait = w.landed_at - w.asked_at}
							<tr>
								<td class="whitespace-nowrap text-ink-muted">{clock(w.asked_at)}</td>
								<td class="num">{secs(wait)}</td>
								<td>{where(w)}{w.c3_hidden ? `, ${w.c3_hidden} out of view` : ''}</td>
								<td class="num">{w.c3_pieces ?? '—'}</td>
								<td class="num">{w.c2_pieces ?? '—'}</td>
								<td class="num text-ink-muted">{pct((w.c3_moving_s ?? 0) / wait)}</td>
								<td class="num text-ink-muted">{pct((w.chute_s ?? 0) / wait)}</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
	</Panel>
</div>

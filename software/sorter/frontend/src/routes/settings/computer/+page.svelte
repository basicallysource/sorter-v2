<script lang="ts">
	// The computer inside the machine (backend computer_health.py, GET
	// /api/system/computer): temperatures against the chip's own limits, whether
	// the kernel is slowing it down to cool it, speed, load, memory, storage,
	// power, clock, and the backend process. Every number is a reading the
	// backend took; what is worked out from readings says so.
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Alert from '$lib/components/ui/Alert.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import ComputerHealthChart, {
		type HealthPoint
	} from '$lib/components/settings/ComputerHealthChart.svelte';

	type Temperature = {
		key: string;
		label: string;
		temp_c: number | null;
		slows_c: number | null;
		hot_c: number;
		critical_c: number | null;
	};
	type Reading = {
		captured_at: number;
		model: string | null;
		temperatures: Temperature[];
		slowing: {
			active: boolean | null;
			recent_share: number | null;
			by: { label: string; state: number; max_state: number }[];
		};
		clusters: { cpus: string; mhz: number | null; max_mhz: number | null; limit_mhz: number | null }[];
		cpu: { use_pct: number | null; cores_pct: number[]; load: number[] | null; count: number | null };
		memory: {
			total_bytes: number;
			available_bytes: number;
			used_pct: number;
			swap_total_bytes: number;
			swap_used_bytes: number;
		} | null;
		storage: {
			path: string;
			total_bytes?: number;
			free_bytes?: number;
			used_pct?: number;
			read_only?: boolean;
			file_system?: string;
			errors?: number | null;
			medium?: { kind: string; name: string | null; wear_pct?: number | null; reserve?: string | null } | null;
		} | null;
		power: { low: boolean | null };
		fans: { label: string; pct: number | null; rpm: number | null }[];
		uptime_s: number | null;
		clock_synced: boolean | null;
	};
	type Lag = { p90: number; max: number } | null;
	type Health = {
		sampling: boolean;
		sample_interval_s: number;
		reading: Reading | null;
		process: {
			rss_bytes: number | null;
			threads: number | null;
			cpu_pct: number | null;
			uptime_s: number;
			starts: number | null;
			unexpected_exits: number | null;
			loop_lag_ms: Lag;
			control_wait_ms: Lag;
		};
		warnings: { kind: string; title: string; since: number | null }[];
		limits: { throttle_window_s: number };
		history: (HealthPoint & { cpu_pct: number | null; mem_pct: number | null })[];
	};

	const SPANS = [
		{ value: '1', label: '1 hour' },
		{ value: '6', label: '6 hours' },
		{ value: '24', label: '24 hours' }
	];
	const NOT_REPORTED = 'Not reported by this computer';

	const machine = getMachineContext();
	let span = $state('6');
	let health = $state<Health | null>(null);
	let error = $state<string | null>(null);

	function base(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	async function load() {
		try {
			const res = await fetch(`${base()}/api/system/computer?hours=${span}`);
			if (!res.ok) throw new Error(`The machine answered ${res.status}.`);
			health = (await res.json()) as Health;
			error = null;
		} catch (e) {
			error = e instanceof Error && e.message ? e.message : 'The machine did not answer.';
		}
	}

	// Every reading the backend takes (each 5 s); the effect also loads at
	// once, and again when the span changes.
	onMount(() => {
		const timer = setInterval(() => void load(), 5000);
		return () => clearInterval(timer);
	});

	$effect(() => {
		void span;
		void load();
	});

	const reading = $derived(health?.reading ?? null);
	const temps = $derived(
		(reading?.temperatures ?? []).filter((t): t is Temperature & { temp_c: number } => t.temp_c != null)
	);
	// The sensor nearest its own limit.
	const hottest = $derived(
		temps.length ? temps.reduce((a, b) => (b.temp_c - b.hot_c > a.temp_c - a.hot_c ? b : a)) : null
	);
	const chipLimits = $derived(
		(reading?.temperatures ?? []).find((t) => t.slows_c != null) ?? hottest
	);
	const now = $derived(reading?.captured_at ?? Date.now() / 1000);

	function gb(bytes: number | null | undefined): string {
		if (bytes == null) return NOT_REPORTED;
		return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;
	}
	function pct(value: number | null | undefined): string {
		return value == null ? NOT_REPORTED : `${Math.round(value)}%`;
	}
	function duration(seconds: number | null | undefined): string {
		if (seconds == null) return NOT_REPORTED;
		const d = Math.floor(seconds / 86400);
		const h = Math.floor((seconds % 86400) / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		if (d > 0) return `${d} d ${h} h`;
		if (h > 0) return `${h} h ${m} min`;
		return `${m} min`;
	}
	function clock(t: number | null): string {
		if (t == null) return '';
		return new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true });
	}
	function degrees(c: number | null | undefined): string {
		return c == null ? 'Not set' : `${c.toFixed(0)} °C`;
	}
	function lag(value: Lag): string {
		return value ? `${value.p90} ms usually, ${value.max} ms at most` : 'Not measured yet';
	}
	function times(n: number): string {
		return n === 1 ? '1 time' : `${n} times`;
	}

	const tempTone = $derived<'warning' | 'danger' | undefined>(
		hottest == null
			? undefined
			: hottest.temp_c >= hottest.hot_c
				? 'danger'
				: hottest.slows_c != null && hottest.temp_c >= hottest.slows_c
					? 'warning'
					: undefined
	);
	const slowedNow = $derived(reading?.slowing.by.filter((d) => d.state > 0) ?? []);
	const storage = $derived(reading?.storage ?? null);
	const memory = $derived(reading?.memory ?? null);

	const stats = $derived([
		{
			label: 'Hottest',
			value: hottest ? hottest.temp_c.toFixed(1) : 'None',
			unit: hottest ? '°C' : undefined,
			hint: hottest ? `${hottest.label}, too hot at ${hottest.hot_c} °C` : 'No temperature sensor',
			tone: tempTone
		},
		{
			label: 'Slowing down to cool',
			value: reading?.slowing.active == null ? 'Unknown' : reading.slowing.active ? 'Yes' : 'No',
			hint:
				reading?.slowing.active == null
					? NOT_REPORTED
					: slowedNow.length
						? slowedNow.map((d) => d.label).join(', ')
						: reading.slowing.recent_share != null
							? `${Math.round(reading.slowing.recent_share * 100)}% of the last ${Math.round((health?.limits.throttle_window_s ?? 120) / 60)} minutes`
							: 'Full speed allowed',
			tone: reading?.slowing.active ? ('warning' as const) : undefined
		},
		{
			label: 'Processor use',
			value: reading?.cpu.use_pct != null ? Math.round(reading.cpu.use_pct).toString() : 'None',
			unit: reading?.cpu.use_pct != null ? '%' : undefined,
			hint: reading?.cpu.load ? `Load ${reading.cpu.load[0].toFixed(2)} on ${reading.cpu.count} cores` : undefined
		},
		{
			label: 'Memory used',
			value: memory ? Math.round(memory.used_pct).toString() : 'None',
			unit: memory ? '%' : undefined,
			hint: memory ? `${gb(memory.available_bytes)} free` : NOT_REPORTED,
			tone: memory && memory.used_pct >= 95 ? ('danger' as const) : undefined
		},
		{
			label: 'Storage used',
			value: storage?.used_pct != null ? Math.round(storage.used_pct).toString() : 'None',
			unit: storage?.used_pct != null ? '%' : undefined,
			hint: storage?.free_bytes != null ? `${gb(storage.free_bytes)} free` : NOT_REPORTED,
			tone: storage?.read_only
				? ('danger' as const)
				: health?.warnings.some((w) => w.kind === 'computer_disk_full')
					? ('warning' as const)
					: undefined
		},
		{
			label: 'Running for',
			value: reading?.uptime_s != null ? duration(reading.uptime_s) : 'Unknown',
			hint:
				reading?.clock_synced == null
					? 'Clock sync not reported'
					: reading.clock_synced
						? 'Clock synchronized'
						: 'Clock not synchronized',
			tone: reading?.clock_synced === false ? ('warning' as const) : undefined
		}
	]);

	const memoryItems = $derived([
		{
			label: 'Memory used',
			value: memory
				? `${gb(memory.total_bytes - memory.available_bytes)} of ${gb(memory.total_bytes)}`
				: NOT_REPORTED
		},
		{
			label: 'Swap used',
			value: memory
				? memory.swap_total_bytes
					? `${gb(memory.swap_used_bytes)} of ${gb(memory.swap_total_bytes)}`
					: 'No swap'
				: NOT_REPORTED
		},
		{
			label: 'Storage free',
			value:
				storage?.free_bytes != null ? `${gb(storage.free_bytes)} of ${gb(storage.total_bytes)}` : NOT_REPORTED
		},
		{
			label: 'Storage',
			value: storage?.medium
				? [storage.medium.kind, storage.medium.name].filter(Boolean).join(', ')
				: NOT_REPORTED
		},
		{
			label: 'Read-only',
			value: storage?.read_only == null ? NOT_REPORTED : storage.read_only ? 'Yes, nothing new is saved' : 'No'
		},
		{
			label: 'Errors the file system recorded',
			value: storage?.errors == null ? NOT_REPORTED : String(storage.errors)
		},
		...(storage?.medium?.wear_pct != null
			? [{ label: 'Rated life used, by its own count', value: `Up to ${storage.medium.wear_pct}%` }]
			: []),
		...(storage?.medium?.reserve
			? [{ label: 'Spare blocks, by its own count', value: storage.medium.reserve }]
			: []),
		{ label: 'Data folder', value: storage?.path ?? NOT_REPORTED, mono: true }
	]);

	const systemItems = $derived([
		{ label: 'Computer', value: reading?.model ?? NOT_REPORTED },
		{
			label: 'Supply voltage',
			value: reading?.power.low == null ? NOT_REPORTED : reading.power.low ? 'Too low' : 'Normal'
		},
		...(reading?.fans.length
			? reading.fans.map((f, i) => ({
					label: reading.fans.length > 1 ? `Fan ${i + 1}` : 'Fan',
					value: [f.pct != null ? `driven at ${f.pct}%` : null, f.rpm != null ? `${f.rpm} rpm` : null]
						.filter(Boolean)
						.join(', ')
				}))
			: [{ label: 'Fan', value: NOT_REPORTED }]),
		{ label: 'Running for', value: duration(reading?.uptime_s) },
		{
			label: 'Clock',
			value:
				reading?.clock_synced == null
					? NOT_REPORTED
					: reading.clock_synced
						? 'Synchronized'
						: 'Not synchronized, times may be off'
		},
		{
			label: 'Load, last 1, 5 and 15 minutes',
			value: reading?.cpu.load ? reading.cpu.load.map((v) => v.toFixed(2)).join(', ') : NOT_REPORTED
		},
		{
			label: 'Use by core',
			value: reading?.cpu.cores_pct.length
				? reading.cpu.cores_pct.map((v) => `${Math.round(v)}%`).join(' ')
				: NOT_REPORTED
		}
	]);

	const processItems = $derived.by(() => {
		const p = health?.process;
		if (!p) return [];
		return [
			{ label: 'Memory', value: gb(p.rss_bytes) },
			{ label: 'Processor, share of one core', value: pct(p.cpu_pct) },
			{ label: 'Threads', value: p.threads == null ? NOT_REPORTED : String(p.threads) },
			{ label: 'Running for', value: duration(p.uptime_s) },
			{
				label: 'Started since the service started',
				value: p.starts == null ? 'Not run by the supervisor' : times(p.starts)
			},
			...(p.unexpected_exits != null
				? [{ label: 'Stopped on its own', value: p.unexpected_exits === 0 ? 'Never' : times(p.unexpected_exits) }]
				: []),
			{ label: 'Web server delay', value: lag(p.loop_lag_ms) },
			{ label: 'Control loop waiting', value: lag(p.control_wait_ms) }
		];
	});
</script>

<svelte:head><title>Sorter - Computer</title></svelte:head>

<div class="flex flex-col gap-(--gap-panels)">
	<PageHeader
		title="Computer"
		description="The computer inside the machine: how hot it runs, whether it is slowing itself down to cool off, and how much memory and storage it has left."
	/>

	{#if error}<Alert tone="danger" title="Could not read the computer's health">{error}</Alert>{/if}
	{#each health?.warnings ?? [] as warning (warning.kind)}
		<Alert tone="warning" title={warning.title}>
			{warning.since ? `Since ${clock(warning.since)}. ` : ''}The dashboard shows what to do.
		</Alert>
	{/each}
	{#if health && !health.sampling}
		<Alert tone="info" title="Readings only while this page is open">
			The backend is not sampling the computer, so there is no history and no warnings.
		</Alert>
	{/if}

	{#if !health && !error}
		<div class="flex justify-center py-10"><Spinner /></div>
	{:else if reading}
		<Panel flush>
			<div class="grid grid-cols-2 gap-px bg-line md:grid-cols-3">
				{#each stats as item (item.label)}
					<div class="bg-surface"><Stat {...item} /></div>
				{/each}
			</div>
		</Panel>

		<Panel
			title="Temperature"
			description="The hottest sensor, one point a minute. Shaded minutes: the computer was slowing itself down to cool off in at least one reading."
		>
			{#snippet actions()}
				<SegmentedControl bind:value={span} options={SPANS} label="Time span" size="sm" />
			{/snippet}
			<ComputerHealthChart
				points={health?.history ?? []}
				from={now - Number(span) * 3600}
				to={now}
				hotC={chipLimits?.hot_c ?? null}
				slowsC={chipLimits?.slows_c ?? null}
			/>
		</Panel>

		<Panel title="Sensors" description="Limits come from the chip's own settings where it has them." flush>
			{#if reading.temperatures.length === 0}
				<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">{NOT_REPORTED}.</p>
			{:else}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th>Sensor</th>
								<th class="num">Now</th>
								<th class="num">Starts slowing down</th>
								<th class="num">Too hot</th>
								<th class="num">Shuts down</th>
							</tr>
						</thead>
						<tbody>
							{#each reading.temperatures as t (t.key)}
								<tr>
									<td>{t.label}</td>
									<td
										class="num {t.temp_c != null && t.temp_c >= t.hot_c
											? 'text-danger-ink'
											: t.temp_c != null && t.slows_c != null && t.temp_c >= t.slows_c
												? 'text-warning-ink'
												: ''}">{t.temp_c != null ? `${t.temp_c.toFixed(1)} °C` : 'No reading'}</td
									>
									<td class="num">{degrees(t.slows_c)}</td>
									<td class="num">{degrees(t.hot_c)}</td>
									<td class="num">{degrees(t.critical_c)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Panel>

		<Panel
			title="Processor speed"
			description="To cool the chip the kernel lowers the speed each group of cores is allowed."
			flush
		>
			{#if reading.clusters.length === 0}
				<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">{NOT_REPORTED}.</p>
			{:else}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th>Cores</th>
								<th class="num">Now</th>
								<th class="num">Allowed</th>
								<th class="num">Top speed</th>
							</tr>
						</thead>
						<tbody>
							{#each reading.clusters as c (c.cpus)}
								<tr>
									<td>{c.cpus}</td>
									<td class="num">{c.mhz != null ? `${c.mhz} MHz` : 'No reading'}</td>
									<td
										class="num {c.limit_mhz != null && c.max_mhz != null && c.limit_mhz < c.max_mhz
											? 'text-warning-ink'
											: ''}">{c.limit_mhz != null ? `${c.limit_mhz} MHz` : 'No reading'}</td
									>
									<td class="num">{c.max_mhz != null ? `${c.max_mhz} MHz` : 'No reading'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
			{#if reading.slowing.by.length}
				<div class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
					Slowed down now:
					{slowedNow.length
						? slowedNow.map((d) => `${d.label} (step ${d.state} of ${d.max_state})`).join(', ')
						: 'nothing'}.
				</div>
			{/if}
		</Panel>

		<div class="grid gap-(--gap-panels) lg:grid-cols-2">
			<Panel title="Memory and storage">
				<KeyValue items={memoryItems} />
			</Panel>
			<Panel title="Power, fan and load">
				<KeyValue items={systemItems} />
			</Panel>
		</div>

		<Panel title="Backend" description="The program that runs the machine.">
			<KeyValue items={processItems} />
		</Panel>
	{/if}
</div>

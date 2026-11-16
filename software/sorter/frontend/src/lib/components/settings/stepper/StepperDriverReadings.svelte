<!--
	What a motor's driver has been reporting, from the record the backend keeps
	all the time ($lib/api/drivers), read again every two seconds while the page
	is open: the driver's fault in words when it has one, with what the machine
	did to recover, and one small graph each of load, current, speed, drive and
	tuning over one time axis. The times the driver warned of heat, overheated,
	saw a short circuit or shut down are marked on that axis.

	On a machine whose record is switched off it is one line saying so. On a
	backend from before the record, and for a motor the record does not keep,
	there is nothing to show, so it shows nothing.

	It is small, and it sits inside the motor's driver settings, which are
	closed until someone opens them (`part="graphs"`). What has to be seen
	whatever is open, that the driver has a fault and what the machine did
	about it, is a part of its own to put above them (`part="fault"`): it
	shows nothing while all is well.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { ApiError } from '$lib/api/http';
	import {
		getDriverHistory,
		getDrivers,
		type DriverFault,
		type DriverSample,
		type DriverState
	} from '$lib/api/drivers';
	import Alert from '$lib/components/ui/Alert.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import StepperDriverReadingChart from './StepperDriverReadingChart.svelte';

	let {
		stepperKey,
		base,
		runCurrent = null,
		holdCurrent = null,
		part = 'graphs'
	}: {
		// The motor's name, as /api/stepper/{name}/tmc takes it.
		stepperKey: string;
		// The backend's address.
		base: string;
		// The run and hold currents the driver is set to (0 to 31), drawn as
		// lines on the current's graph; null until they are read.
		runCurrent?: number | null;
		holdCurrent?: number | null;
		part?: 'graphs' | 'fault';
	} = $props();

	const REFRESH_MS = 2000;
	const WINDOWS = [
		{ value: '60', label: '1 minute', words: 'the last minute' },
		{ value: '600', label: '10 minutes', words: 'the last 10 minutes' },
		{ value: '3600', label: '1 hour', words: 'the last hour' }
	];

	// The time asked for, and the time the readings on the page were asked with:
	// the graphs change over when the new readings arrive.
	let chosen = $state('600');
	let shownSeconds = $state(600);

	// 'waiting' until the backend answers; 'none' when it has no record to ask.
	let status = $state<'waiting' | 'on' | 'off' | 'none'>('waiting');
	let samples = $state.raw<DriverSample[]>([]);
	let driver = $state.raw<DriverState | null>(null);
	// Where the pointer is across the graphs, 0 to 1, on whichever graph it is.
	// A share and not a time, so the mark stays under the pointer as new
	// readings move the axis on.
	let hoverShare = $state<number | null>(null);

	// What steers the loading; nothing is drawn from these.
	let loadedFor = '';
	let loading: AbortSignal | null = null;
	// The backend is from before the driver record: it is not asked again.
	let stopped = false;
	// The record did not know this motor when its readings were last asked for:
	// they are asked for again once the list of drivers names it.
	let notKept = false;

	// The backend has no such route, or no such motor.
	function notThere(reason: unknown): boolean {
		return reason instanceof ApiError && (reason.status === 404 || reason.status === 405);
	}

	async function load(name: string, baseUrl: string, seconds: number, signal: AbortSignal) {
		if (stopped || loading === signal) return;
		loading = signal;
		const [list, history] = await Promise.allSettled([
			getDrivers(baseUrl, signal),
			notKept || part === 'fault' ? null : getDriverHistory(baseUrl, name, seconds, signal)
		]);
		if (loading === signal) loading = null;
		if (signal.aborted) return;

		if (list.status === 'rejected' && notThere(list.reason)) {
			stopped = true;
			status = 'none';
			return;
		}
		const switchedOff =
			(list.status === 'fulfilled' && list.value?.enabled === false) ||
			(history.status === 'fulfilled' && history.value?.enabled === false);
		if (switchedOff) {
			status = 'off';
			samples = [];
			driver = null;
			return;
		}
		if (list.status === 'fulfilled') {
			const drivers = Array.isArray(list.value?.drivers) ? list.value.drivers : [];
			driver = drivers.find((d) => d.name === name) ?? null;
			if (driver) notKept = false;
			// The fault alone needs no readings.
			if (part === 'fault') status = 'on';
		}
		if (history.status === 'rejected') {
			// Any other failure (the machine did not answer) keeps what is on the
			// page; the next round asks again.
			if (notThere(history.reason)) {
				notKept = true;
				status = 'none';
				samples = [];
			}
		} else if (history.value) {
			samples = Array.isArray(history.value.samples) ? history.value.samples : [];
			shownSeconds = seconds;
			status = 'on';
		}
	}

	// Reads at once, then every two seconds while the page is in view, and again
	// at once when the motor, the machine or the time shown changes.
	$effect(() => {
		const name = stepperKey;
		const baseUrl = base;
		const seconds = Number(chosen);
		const controller = new AbortController();
		const round = () => {
			if (document.visibilityState !== 'hidden') {
				void load(name, baseUrl, seconds, controller.signal);
			}
		};
		untrack(() => {
			const key = `${baseUrl} ${name}`;
			if (key !== loadedFor) {
				loadedFor = key;
				stopped = false;
				notKept = false;
				status = 'waiting';
				samples = [];
				driver = null;
				hoverShare = null;
			}
			round();
		});
		const timer = setInterval(round, REFRESH_MS);
		return () => {
			clearInterval(timer);
			controller.abort();
		};
	});

	// --- The driver's state in words ---

	type FaultLook = { tone: 'danger' | 'warning'; title: string };
	const FAULTS: Record<DriverFault['kind'], FaultLook> = {
		shut_down: { tone: 'danger', title: 'The driver shut the motor off' },
		overheated: { tone: 'danger', title: 'The driver overheated' },
		overheating: { tone: 'warning', title: 'The driver is running hot' },
		tuning_out_of_range: {
			tone: 'warning',
			title: "The driver's automatic tuning is out of range"
		}
	};
	// A kind of fault this page was not written for still gets its sentence.
	const OTHER_FAULT: FaultLook = { tone: 'danger', title: 'The driver reports a fault' };
	const fault = $derived(driver?.fault ?? null);
	const faultLook = $derived<FaultLook | null>(
		fault ? (FAULTS[fault.kind] ?? OTHER_FAULT) : null
	);
	// The five latest, newest first.
	const recoveries = $derived(
		[...(driver?.recoveries ?? [])].sort((a, b) => b.t - a.t).slice(0, 5)
	);

	// --- The time axis ---

	// The machine's clock is the only clock here: the axis ends at its newest
	// reading, so a browser whose clock differs draws the same graph.
	const newest = $derived(samples.length > 0 ? samples[samples.length - 1] : null);
	const to = $derived(newest?.t ?? 0);
	const from = $derived(to - shownSeconds);
	const period = $derived(
		WINDOWS.find((w) => Number(w.value) === shownSeconds)?.words ?? 'the time shown'
	);

	// The record is read at its own pace, so a gap is judged against it: four
	// times the usual wait between two readings, and never under ten seconds.
	const breakAfter = $derived.by(() => {
		if (samples.length < 3) return 10;
		const waits: number[] = [];
		for (let i = 1; i < samples.length; i++) waits.push(samples[i].t - samples[i - 1].t);
		waits.sort((a, b) => a - b);
		return Math.max(10, 4 * waits[Math.floor(waits.length / 2)]);
	});

	// The reading nearest the pointer.
	const cursor = $derived.by(() => {
		if (hoverShare === null || samples.length === 0) return null;
		const hoverT = from + hoverShare * (to - from);
		let lo = 0;
		let hi = samples.length - 1;
		while (lo < hi) {
			const mid = (lo + hi) >> 1;
			if (samples[mid].t < hoverT) lo = mid + 1;
			else hi = mid;
		}
		if (lo > 0 && hoverT - samples[lo - 1].t <= samples[lo].t - hoverT) return samples[lo - 1];
		return samples[lo];
	});

	function setHover(share: number | null) {
		hoverShare = share;
	}

	// --- What the driver flagged, as stretches of the time axis ---

	type Mark = { from: number; to: number; danger: boolean; what: string };

	function flagsOf(sample: DriverSample): string {
		const flags: string[] = [];
		if (sample.shut_down) flags.push('shut down');
		if (sample.short) flags.push('short circuit');
		if (sample.overheated) flags.push('overheated');
		if (sample.overheating) flags.push('heat warning');
		return flags.join(', ');
	}

	const marks = $derived.by(() => {
		const out: Mark[] = [];
		let open: Mark | null = null;
		for (const sample of samples) {
			const what = flagsOf(sample);
			if (!what || sample.t < from) {
				open = null;
				continue;
			}
			if (open && open.what === what && sample.t - open.to <= breakAfter) {
				open.to = sample.t;
				continue;
			}
			open = {
				from: sample.t,
				to: sample.t,
				danger: sample.shut_down || sample.short || sample.overheated,
				what
			};
			out.push(open);
		}
		return out;
	});

	// A mark is at least this wide, as a share of the axis, so one reading shows.
	const MARK_MIN = 0.8;
	function markBox(mark: Mark): { x: number; width: number } {
		const span = Math.max(1, to - from);
		const start = ((mark.from - from) / span) * 100;
		const width = Math.max(MARK_MIN, ((mark.to - mark.from) / span) * 100);
		return { x: Math.max(0, Math.min(start, 100 - width)), width };
	}

	function markTitle(mark: Mark): string {
		const until = mark.to > mark.from ? ` to ${clock(mark.to)}` : '';
		return `${clock(mark.from)}${until}: ${mark.what}`;
	}

	// --- Times and numbers in words ---

	function clock(t: number, seconds = true): string {
		return new Date(t * 1000).toLocaleTimeString([], {
			hour: 'numeric',
			minute: '2-digit',
			second: seconds ? '2-digit' : undefined,
			hour12: true
		});
	}
	// A time on the axis: to the second, but to the minute across an hour.
	function axisClock(t: number): string {
		return clock(t, shownSeconds <= 600);
	}
	// A time that may be days back: with its date unless it is today.
	function when(t: number): string {
		const date = new Date(t * 1000);
		if (date.toDateString() === new Date().toDateString()) return clock(t);
		return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${clock(t)}`;
	}
	function whole(value: number): string {
		return Math.round(value).toLocaleString();
	}

	const currentLines = $derived([
		...(runCurrent === null
			? []
			: [{ value: runCurrent, label: `Run current, ${runCurrent} of 31` }]),
		...(holdCurrent === null
			? []
			: [{ value: holdCurrent, label: `Hold current, ${holdCurrent} of 31`, dotted: true }])
	]);
</script>

{#snippet recoveryList()}
	<ul class="flex flex-col gap-1">
		{#each recoveries as recovery, i (i)}
			<li class="flex flex-wrap items-baseline gap-x-3">
				<span class="num shrink-0 text-ink-muted">{when(recovery.t)}</span>
				<span class="min-w-0 flex-1">{recovery.what}</span>
				<span class="shrink-0 font-medium {recovery.ok ? 'text-success-ink' : 'text-danger-ink'}">
					{recovery.ok ? 'Worked' : 'Did not work'}
				</span>
			</li>
		{/each}
	</ul>
{/snippet}

<!-- What the five graphs share. The pointer's reading is passed to each on its
     own: in with these, every move of the pointer would have each graph work
     out its line again. -->
{#snippet graphs()}
	{@const shared = { samples, from, to, breakAfter, period, onhover: setHover }}
	<div class="flex flex-col gap-2">
		<StepperDriverReadingChart
			{...shared}
			{cursor}
			title="Load"
			caption="How freely the motor turns (SG_RESULT, 0 to 510), drawn only while it moves. Low is a heavy load; near 0 is a stall."
			read={(s) => (s.moving ? s.sg_result : null)}
			max={510}
			ticks={[510, 255, 0]}
			format={(v) => `${whole(v)} of 510`}
			none="Not moving"
		/>
		<StepperDriverReadingChart
			{...shared}
			{cursor}
			title="Current"
			caption="The driver's current at that moment (CS_ACTUAL, 0 to 31): up at the run current for a move, down to the hold current a few seconds after. Still at the run current long after a move, the motor runs hot."
			read={(s) => s.cs_actual}
			max={31}
			ticks={[31, 16, 0]}
			format={(v) => `${whole(v)} of 31`}
			refs={currentLines}
		/>
		<StepperDriverReadingChart
			{...shared}
			{cursor}
			title="Speed"
			caption="How fast the driver is being stepped, in full steps a second. It is the speed asked for, not the shaft's, so it stays up through a stall: read it beside the load."
			read={(s) => s.full_steps_per_s}
			least={100}
			format={(v) => `${whole(v)} full steps/s`}
		/>
		<StepperDriverReadingChart
			{...shared}
			{cursor}
			title="Drive"
			caption="How much of its supply voltage the driver is using (PWM_SCALE_SUM, 0 to 255). Pinned at 255, it has no voltage left to hold the set current."
			read={(s) => s.pwm_scale_sum}
			max={255}
			ticks={[255, 128, 0]}
			format={(v) => `${whole(v)} of 255`}
		/>
		<StepperDriverReadingChart
			{...shared}
			{cursor}
			title="Tuning"
			caption="The driver's automatic tuning (PWM_OFS_AUTO, 0 to 255). It normally sits in a steady band; a jump means the tuning went wrong."
			read={(s) => s.pwm_ofs_auto}
			max={255}
			ticks={[255, 128, 0]}
			format={(v) => `${whole(v)} of 255`}
		/>

		<!-- The time axis the five share, under the last of them and as wide as
		     their graphs, with what the driver flagged marked on it. -->
		<div class="ml-[8.75rem]">
			{#if marks.length > 0}
				<svg
					viewBox="0 0 100 100"
					preserveAspectRatio="none"
					class="mb-1.5 block h-2 w-full"
					role="img"
					aria-label="When the driver warned of heat, overheated, saw a short circuit or shut down, over {period}"
				>
					{#each marks as mark, i (i)}
						{@const box = markBox(mark)}
						<rect
							x={box.x}
							y="0"
							width={box.width}
							height="100"
							fill={mark.danger ? 'var(--danger)' : 'var(--warning)'}
						>
							<title>{markTitle(mark)}</title>
						</rect>
					{/each}
				</svg>
			{/if}
			<div class="num flex justify-between text-xs text-ink-muted">
				<span>{axisClock(from)}</span>
				<span>{axisClock((from + to) / 2)}</span>
				<span>{axisClock(to)}</span>
			</div>
			{#if marks.length > 0}
				<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
					{#if marks.some((mark) => !mark.danger)}
						<span class="flex items-center gap-1.5">
							<span class="h-2 w-3 bg-warning"></span>Heat warning
						</span>
					{/if}
					{#if marks.some((mark) => mark.danger)}
						<span class="flex items-center gap-1.5">
							<span class="h-2 w-3 bg-danger"></span>Overheated, short circuit or shut down
						</span>
					{/if}
				</div>
			{/if}
		</div>
	</div>
{/snippet}

{#snippet faultAlert()}
	{#if fault && faultLook}
		<Alert tone={faultLook.tone} title={faultLook.title}>
			<p>{fault.detail}</p>
			<p class="num text-ink-muted">Since {when(fault.since)}.</p>
			{#if recoveries.length > 0}
				<p class="mt-2 font-medium">What the machine did to recover</p>
				<div class="mt-1">{@render recoveryList()}</div>
			{/if}
		</Alert>
	{/if}
{/snippet}

{#if part === 'fault'}
	{#if status === 'on' && fault && faultLook}
		<div class="px-(--pad-panel) py-3">{@render faultAlert()}</div>
	{/if}
{:else if status === 'on' || status === 'off'}
	<section class="px-(--pad-panel) py-(--pad-row)">
		<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
			<h3 class="text-sm font-medium text-ink">
				Driver readings
				{#if status === 'on'}
					<span class="num ml-2 font-normal text-ink-muted">
						{#if cursor}at {clock(cursor.t)}{:else if newest}newest {clock(newest.t)}{/if}
					</span>
				{/if}
			</h3>
			{#if status === 'on'}
				<SegmentedControl bind:value={chosen} options={WINDOWS} label="Time shown" size="sm" />
			{/if}
		</div>
		{#if status === 'off'}
			<p class="mt-1 text-sm text-ink-muted">The driver record is switched off on this machine.</p>
		{:else if samples.length === 0}
			<p class="mt-2 text-sm text-ink-muted">
				No readings in {period}.{driver?.latest ? ` The newest is from ${when(driver.latest.t)}.` : ''}
			</p>
		{:else}
			<div class="mt-3">{@render graphs()}</div>
		{/if}
	</section>
{/if}

<!--
	A motor's automatic StallGuard tuning: on or off, what normal running reads,
	and the trigger and speed floor that come from it. The backend learns and
	sets them (stallguard_tuner.py) while the motor runs; this shows it, and
	shows nothing for a motor it does not tune.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import { fmtTime, type AutoTuning } from '$lib/settings/stallguard';

	let {
		motor,
		label,
		base,
		auto = $bindable(false),
		onchange
	}: {
		// The motor's name in the API: 'chute'.
		motor: string;
		// What the page calls it, in a sentence.
		label: string;
		base: () => string;
		// Whether it is on, for the forms beside it.
		auto?: boolean;
		// It set the threshold or floor, or was turned on or off.
		onchange?: () => void;
	} = $props();

	const POLL_MS = 4000;

	let tuning = $state<AutoTuning | null>(null);
	let saving = $state(false);
	let error = $state<string | null>(null);

	async function readError(res: Response): Promise<string> {
		const body = await res.json().catch(() => ({}));
		return typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`;
	}

	function take(next: AutoTuning) {
		const lastChange = tuning?.changes?.[0]?.at;
		const changed =
			tuning !== null && (next.auto !== tuning.auto || next.changes?.[0]?.at !== lastChange);
		tuning = next;
		auto = next.auto;
		if (changed) onchange?.();
	}

	async function load() {
		try {
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-auto`);
			if (!res.ok) throw new Error(await readError(res));
			take(await res.json());
			error = null;
		} catch (e: any) {
			error = e.message ?? 'Failed to read the automatic tuning';
		}
	}

	async function send(body: { enabled?: boolean; learn_again?: boolean }) {
		saving = true;
		error = null;
		try {
			const res = await fetch(`${base()}/stepper/${motor}/stallguard-auto`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
			if (!res.ok) throw new Error(await readError(res));
			take(await res.json());
			onchange?.();
		} catch (e: any) {
			error = e.message ?? 'Failed to change the automatic tuning';
		} finally {
			saving = false;
		}
	}

	onMount(() => {
		void load();
		const timer = setInterval(load, POLL_MS);
		return () => clearInterval(timer);
	});

	const on = $derived(!!tuning?.auto && !!tuning?.running);
	const lastChange = $derived(tuning?.changes?.[0] ?? null);
	const facts = $derived.by(() => {
		const t = tuning;
		if (!t || !on) return [];
		const items: { label: string; value: string }[] = [];
		if (t.trigger != null) items.push({ label: 'Trips at', value: `${t.trigger} or lower` });
		items.push({
			label: 'Normal running',
			value: t.normal_low != null ? `${t.normal_low} or higher` : 'Still learning'
		});
		if (t.tcoolthrs != null)
			items.push({
				label: 'Speed floor',
				value:
					t.floor_speed != null
						? `${t.tcoolthrs}, checks above ${t.floor_speed.toLocaleString()} µsteps/s`
						: `${t.tcoolthrs}`
			});
		items.push({
			label: 'Learned from',
			value: `${(t.learned_from ?? 0).toLocaleString()} readings`
		});
		if (lastChange)
			items.push({
				label: 'Last change',
				value: `${fmtTime(lastChange.at)}: trips at ${lastChange.sgthrs[0] != null ? 2 * lastChange.sgthrs[0] : '–'} → ${2 * lastChange.sgthrs[1]}`
			});
		return items;
	});
</script>

{#if tuning?.supported}
	<Panel title="Automatic tuning" description="Sets the trigger from how {label} runs." flush>
		{#snippet actions()}
			{#if !on}
				<Badge>Off</Badge>
			{:else if tuning?.working_harder}
				<Badge tone="warning">Working harder</Badge>
			{:else if tuning?.state === 'tuned'}
				<Badge tone="success">Tuned</Badge>
			{:else if tuning?.state === 'learning'}
				<Badge tone="primary">Learning {tuning.readings ?? 0} of {tuning.needed ?? 0}</Badge>
			{:else if tuning?.state === 'waiting'}
				<Badge>Paused for a recording</Badge>
			{/if}
		{/snippet}
		<div class="divide-y divide-line border-t border-line">
			<SettingRow label="Tune automatically" help="A threshold saved by hand turns it off.">
				<Switch
					checked={tuning.auto}
					label="Tune automatically"
					disabled={saving || !tuning.running}
					onchange={(checked) => send({ enabled: checked })}
				/>
			</SettingRow>
			{#if error || !tuning.running || (on && (tuning.working_harder || tuning.reliable === false || tuning.error))}
				<div class="flex flex-col gap-3 px-(--pad-panel) py-(--pad-row)">
					{#if error}<Alert tone="danger">{error}</Alert>{/if}
					{#if !tuning.running}
						<Alert tone="info">Not running: StallGuard is off on this machine.</Alert>
					{/if}
					{#if on && tuning.working_harder}
						<Alert tone="warning" title="Working harder than it did" actions={learnAgain}>
							Normal running read {tuning.baseline_low} or higher; now {tuning.normal_low}. Check {label}
							turns freely, then learn again.
						</Alert>
					{/if}
					{#if on && tuning.reliable === false}
						<Alert tone="danger" title="Normal running is close to a stall">
							It reads {tuning.normal_low} or higher. A stall still trips it, with little room.
						</Alert>
					{/if}
					{#if on && tuning.error}<Alert tone="danger">{tuning.error}</Alert>{/if}
				</div>
			{/if}
			{#if facts.length > 0}
				<div class="px-(--pad-panel) py-1">
					<KeyValue items={facts} />
				</div>
			{/if}
		</div>
		{#snippet footer()}
			{#if on}
				<Button
					variant="ghost"
					icon={RotateCcw}
					loading={saving}
					onclick={() => send({ learn_again: true })}
				>
					Learn again
				</Button>
			{/if}
		{/snippet}
	</Panel>
{/if}

{#snippet learnAgain()}
	<Button size="sm" loading={saving} onclick={() => send({ learn_again: true })}>Learn again</Button
	>
{/snippet}

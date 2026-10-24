<!--
	The chute's position check: on or off, every how many pieces, and what the
	checks found. Each check finds the home switch the way homing does and reads
	how far the chute had drifted, so it catches lost steps StallGuard can't see
	(subsystems/distribution/position_check.py). Each check also puts the chute
	back on its true position.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import { fmtTime } from '$lib/settings/stallguard';

	type Check = {
		checked_at: number;
		ok: boolean;
		drift_steps: number | null;
		drift_deg: number | null;
		beyond_range: boolean;
		precision_deg: number | null;
		error: string | null;
	};
	type Status = {
		enabled: boolean;
		every: number;
		pieces_since_check: number | null;
		checking: boolean;
		checks: number;
		failed: number;
		lost_steps: number;
		largest_deg: number | null;
		lost_steps_deg: number;
		recent: Check[];
	};

	const POLL_MS = 5000;
	const manager = getMachinesContext();

	let status = $state<Status | null>(null);
	let every = $state<number | null>(null);
	let saving = $state(false);
	let running = $state(false);
	let error = $state<string | null>(null);

	function base(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	async function readError(res: Response): Promise<string> {
		const body = await res.json().catch(() => ({}));
		return typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`;
	}

	async function load() {
		try {
			const res = await fetch(`${base()}/api/hardware-config/chute/position-check`);
			if (!res.ok) throw new Error(await readError(res));
			status = await res.json();
			if (every === null && status) every = status.every;
		} catch (e: any) {
			error = e.message ?? 'Failed to read the position check';
		}
	}

	async function save(changes: { position_check?: boolean; position_check_every?: number }) {
		saving = true;
		error = null;
		try {
			const res = await fetch(`${base()}/api/hardware-config/chute`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(changes)
			});
			if (!res.ok) throw new Error(await readError(res));
			await load();
		} catch (e: any) {
			error = e.message ?? 'Failed to save the position check';
		} finally {
			saving = false;
		}
	}

	async function checkNow() {
		running = true;
		error = null;
		try {
			const res = await fetch(`${base()}/api/hardware-config/chute/position-check/run`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await readError(res));
			await load();
		} catch (e: any) {
			error = e.message ?? 'The check failed';
		} finally {
			running = false;
		}
	}

	function saveEvery() {
		if (every !== null && every >= 1 && status && Math.round(every) !== status.every) {
			void save({ position_check_every: Math.round(every) });
		}
	}

	onMount(() => {
		void load();
		const timer = setInterval(load, POLL_MS);
		return () => clearInterval(timer);
	});

	function driftText(check: Check): string {
		if (!check.ok) return 'Failed';
		if (check.beyond_range) return `${check.drift_deg}° or more`;
		return `${(check.drift_deg ?? 0) >= 0 ? '+' : ''}${check.drift_deg?.toFixed(2)}°`;
	}

	const last = $derived(status?.recent?.[0] ?? null);
	const facts = $derived.by(() => {
		const s = status;
		if (!s) return [];
		const items: { label: string; value: string }[] = [];
		if (last)
			items.push({ label: 'Last check', value: `${driftText(last)}, ${fmtTime(last.checked_at)}` });
		if (s.checks > 0) {
			items.push({ label: 'Lost steps found', value: `${s.lost_steps} of ${s.checks} checks` });
			if (s.largest_deg !== null)
				items.push({ label: 'Largest drift', value: `${s.largest_deg.toFixed(2)}°` });
		}
		if (s.enabled && s.pieces_since_check !== null)
			items.push({
				label: 'Next check',
				value: `in ${Math.max(0, s.every - s.pieces_since_check)} pieces`
			});
		return items;
	});
</script>

<Panel
	title="Position check"
	description="Every few pieces the chute finds its home switch, to catch steps it lost."
	flush
>
	{#snippet actions()}
		{#if status?.checking || running}
			<Badge tone="primary">Checking</Badge>
		{:else if status && status.lost_steps > 0}
			<Badge tone="warning">Lost steps found</Badge>
		{:else if status?.enabled}
			<Badge tone="success">On</Badge>
		{:else}
			<Badge>Off</Badge>
		{/if}
	{/snippet}
	<div class="divide-y divide-line border-t border-line">
		<SettingRow label="Check the position" help="Each check takes about 2 seconds.">
			<Switch
				checked={!!status?.enabled}
				label="Check the position"
				disabled={!status || saving}
				onchange={(checked) => save({ position_check: checked })}
			/>
		</SettingRow>
		<SettingRow label="Every" for="chute-position-check-every">
			<Input
				id="chute-position-check-every"
				type="number"
				size="sm"
				min={1}
				unit="pieces"
				bind:value={every}
				onchange={saveEvery}
				class="w-32"
			/>
		</SettingRow>
		{#if error || (status && status.lost_steps > 0) || (last && !last.ok)}
			<div class="flex flex-col gap-3 px-(--pad-panel) py-(--pad-row)">
				{#if error}<Alert tone="danger">{error}</Alert>{/if}
				{#if last && !last.ok}
					<Alert tone="danger" title="The last check failed">
						{last.error}. Home the chute.
					</Alert>
				{/if}
				{#if status && status.lost_steps > 0}
					<Alert tone="warning" title="It lost steps {status.lost_steps} times">
						Each time it was put back on its position. Pieces since the check before may be in the
						wrong bins.
					</Alert>
				{/if}
			</div>
		{/if}
		{#if facts.length > 0}
			<div class="px-(--pad-panel) py-1">
				<KeyValue items={facts} />
			</div>
		{/if}
	</div>
	{#snippet footer()}
		<span class="mr-auto text-sm text-ink-muted">Pause the machine to check now.</span>
		<Button
			variant="ghost"
			loading={running}
			disabled={!status || status.checking}
			onclick={checkNow}
		>
			Check now
		</Button>
	{/snippet}
</Panel>

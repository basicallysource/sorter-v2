<script lang="ts">
	import { onMount } from 'svelte';
	import { RefreshCw, Save, ToggleLeft, ToggleRight } from 'lucide-svelte';

	type Role = 'c_channel_1' | 'c_channel_2' | 'c_channel_3' | 'classification_channel';

	interface Props {
		baseUrl: string;
		hardwareState: string;
	}

	let { baseUrl, hardwareState }: Props = $props();

	const CHANNELS: { role: Role; label: string }[] = [
		{ role: 'c_channel_1', label: 'C1' },
		{ role: 'c_channel_2', label: 'C2' },
		{ role: 'c_channel_3', label: 'C3' },
		{ role: 'classification_channel', label: 'C4' }
	];

	let speedInputs = $state<Record<Role, string>>({
		c_channel_1: '7',
		c_channel_2: '14',
		c_channel_3: '9',
		classification_channel: '12'
	});
	let defaults = $state<Record<Role, number | null>>({
		c_channel_1: null,
		c_channel_2: null,
		c_channel_3: null,
		classification_channel: null
	});
	let minRpm = $state(0.01);
	let maxRpm = $state(25);
	let maxRpmByRole = $state<Record<Role, number>>({
		c_channel_1: 25,
		c_channel_2: 25,
		c_channel_3: 25,
		classification_channel: 25
	});
	let loading = $state(false);
	let saving = $state(false);
	let mode = $state(false);
	let modeAvailable = $state(false);
	let modeBusy = $state(false);
	let error = $state<string | null>(null);
	let savedAt = $state<number | null>(null);
	let loadedBaseUrl = $state<string | null>(null);

	const modeLabel = $derived(mode ? 'On' : modeAvailable ? 'Off' : 'Unavailable');
	const statusLabel = $derived(savedAt ? 'Saved' : hardwareState);

	function numberFromPayload(value: unknown): number | null {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : null;
	}

	function maxRpmFor(role: Role): number {
		return maxRpmByRole[role] ?? maxRpm;
	}

	function clampSpeed(role: Role, value: unknown): number {
		const parsed = Number(value);
		if (!Number.isFinite(parsed)) return minRpm;
		return Math.min(maxRpmFor(role), Math.max(minRpm, parsed));
	}

	function setSpeed(role: Role, value: string) {
		speedInputs = { ...speedInputs, [role]: value };
		savedAt = null;
	}

	async function loadSpeeds() {
		if (!baseUrl) return;
		loading = true;
		error = null;
		try {
			const res = await fetch(`${baseUrl}/api/system/sample-collection-speeds`);
			const payload = await res.json();
			if (!res.ok || payload?.ok === false) {
				throw new Error(payload?.message ?? payload?.reason ?? 'Could not load speeds');
			}
			minRpm = numberFromPayload(payload.min_rpm) ?? minRpm;
			const payloadMaxRpm = numberFromPayload(payload.max_rpm) ?? maxRpm;
			maxRpm = payloadMaxRpm;
			mode = Boolean(payload.sample_collection_mode);
			modeAvailable = Boolean(payload.sample_collection_mode_available);

			const nextDefaults = { ...defaults };
			const nextSpeedInputs = { ...speedInputs };
			const nextMaxRpmByRole = { ...maxRpmByRole };
			const defaultPayload = payload.default_speeds_rpm_by_role ?? {};
			const effectivePayload = payload.effective_speeds_rpm_by_role ?? {};
			const maxPayload = payload.max_rpm_by_role ?? {};
			for (const channel of CHANNELS) {
				nextMaxRpmByRole[channel.role] =
					numberFromPayload(maxPayload[channel.role]) ?? payloadMaxRpm;
				nextDefaults[channel.role] = numberFromPayload(defaultPayload[channel.role]);
				const nextValue =
					numberFromPayload(effectivePayload[channel.role]) ??
					nextDefaults[channel.role] ??
					Number(nextSpeedInputs[channel.role]);
				if (Number.isFinite(nextValue)) {
					nextSpeedInputs[channel.role] = String(nextValue);
				}
			}
			maxRpmByRole = nextMaxRpmByRole;
			defaults = nextDefaults;
			speedInputs = nextSpeedInputs;
		} catch (e: any) {
			error = e?.message ?? 'Could not load speeds';
		} finally {
			loading = false;
		}
	}

	async function saveSpeeds() {
		if (!baseUrl) return;
		saving = true;
		error = null;
		try {
			const body: Record<Role, number> = {
				c_channel_1: clampSpeed('c_channel_1', speedInputs.c_channel_1),
				c_channel_2: clampSpeed('c_channel_2', speedInputs.c_channel_2),
				c_channel_3: clampSpeed('c_channel_3', speedInputs.c_channel_3),
				classification_channel: clampSpeed(
					'classification_channel',
					speedInputs.classification_channel
				)
			};
			const res = await fetch(`${baseUrl}/api/system/sample-collection-speeds`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ speeds_rpm_by_role: body })
			});
			const payload = await res.json();
			if (!res.ok || payload?.ok === false) {
				throw new Error(payload?.message ?? payload?.reason ?? 'Could not save speeds');
			}
			speedInputs = {
				c_channel_1: String(body.c_channel_1),
				c_channel_2: String(body.c_channel_2),
				c_channel_3: String(body.c_channel_3),
				classification_channel: String(body.classification_channel)
			};
			savedAt = Date.now();
			mode = Boolean(payload.sample_collection_mode);
			modeAvailable = Boolean(payload.sample_collection_mode_available);
		} catch (e: any) {
			error = e?.message ?? 'Could not save speeds';
		} finally {
			saving = false;
		}
	}

	async function toggleMode() {
		if (!baseUrl || !modeAvailable) return;
		modeBusy = true;
		error = null;
		try {
			const res = await fetch(`${baseUrl}/api/system/sample-collection-mode`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled: !mode })
			});
			const payload = await res.json();
			if (!res.ok || payload?.ok === false) {
				throw new Error(payload?.message ?? payload?.reason ?? 'Could not change mode');
			}
			mode = Boolean(payload.enabled);
		} catch (e: any) {
			error = e?.message ?? 'Could not change mode';
		} finally {
			modeBusy = false;
		}
	}

	$effect(() => {
		if (!baseUrl || baseUrl === loadedBaseUrl) return;
		loadedBaseUrl = baseUrl;
		void loadSpeeds();
	});

	onMount(() => {
		void loadSpeeds();
	});
</script>

<div class="flex flex-col gap-3 p-3">
	<div class="flex items-center justify-between gap-3">
		<div class="min-w-0">
			<div class="text-sm font-semibold text-text">Sample Capture</div>
			<div class="text-xs text-text-muted">{statusLabel}</div>
		</div>
		<button
			type="button"
			onclick={() => void toggleMode()}
			disabled={!modeAvailable || modeBusy}
			class="flex items-center gap-1.5 border border-border bg-bg px-2 py-1 text-xs font-medium text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			title={mode ? 'Disable sample mode' : 'Enable sample mode'}
		>
			{#if mode}
				<ToggleRight size={18} class="text-success" />
			{:else}
				<ToggleLeft size={18} class="text-text-muted" />
			{/if}
			<span>{modeLabel}</span>
		</button>
	</div>

	<div class="grid grid-cols-2 gap-2">
		{#each CHANNELS as channel (channel.role)}
			<label class="flex min-w-0 flex-col gap-1">
				<span class="text-xs font-medium text-text-muted">{channel.label}</span>
				<div class="flex items-center border border-border bg-bg">
					<input
							type="number"
							min={minRpm}
							max={maxRpmFor(channel.role)}
						step="0.01"
						value={speedInputs[channel.role]}
						oninput={(event) => setSpeed(channel.role, event.currentTarget.value)}
						onchange={(event) => setSpeed(channel.role, event.currentTarget.value)}
						class="min-w-0 flex-1 bg-transparent px-2 py-1.5 text-sm text-text outline-none"
					/>
					<span class="shrink-0 pr-2 text-[10px] font-medium uppercase text-text-muted">rpm</span>
				</div>
				{#if defaults[channel.role] !== null}
					<span class="text-[10px] text-text-muted">cfg {defaults[channel.role]}</span>
				{/if}
			</label>
		{/each}
	</div>

	<div class="flex items-center justify-between gap-2">
		<button
			type="button"
			onclick={() => void loadSpeeds()}
			disabled={loading || saving}
			class="flex items-center gap-1.5 border border-border bg-bg px-2 py-1 text-xs text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			title="Refresh speeds"
		>
			<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
			<span>Refresh</span>
		</button>
		<button
			type="button"
			onclick={() => void saveSpeeds()}
			disabled={saving || loading}
			class="flex items-center gap-1.5 border border-primary bg-primary px-3 py-1 text-xs font-medium text-white hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
			title="Apply speeds"
		>
			<Save size={14} />
			<span>{saving ? 'Saving' : 'Apply'}</span>
		</button>
	</div>

	{#if error}
		<div class="border border-danger/30 bg-danger/5 px-2 py-1.5 text-xs text-danger">{error}</div>
	{/if}
</div>

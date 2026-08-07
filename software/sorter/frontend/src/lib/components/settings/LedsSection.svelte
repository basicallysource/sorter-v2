<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { ToggleSwitch, Alert } from '$lib/components/primitives';
	import SettingRow from '$lib/components/settings/SettingRow.svelte';

	const machine = getMachineContext();

	const STATUS_POLL_MS = 5000;
	// Applied while dragging the brightness slider so we don't POST per pixel.
	const BRIGHTNESS_DEBOUNCE_MS = 200;

	type LedInfo = {
		board_role: string;
		board_name: string;
		channel: number;
		duty: number;
	};

	let enabled = $state(true);
	let brightnessPercent = $state(100);
	let onAtBoot = $state(true);
	let defaults = $state({ enabled: true, brightness_percent: 100, on_at_boot: true });
	let configured = $state(false);
	let pwmSupported = $state(false);
	let hardwareReady = $state(false);
	let leds = $state<LedInfo[]>([]);

	let loading = $state(true);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);

	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let brightnessTimer: ReturnType<typeof setTimeout> | null = null;

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function applyStatus(payload: any) {
		enabled = Boolean(payload?.enabled);
		onAtBoot = Boolean(payload?.on_at_boot);
		const pct = Number(payload?.brightness_percent);
		if (Number.isFinite(pct)) brightnessPercent = Math.max(0, Math.min(100, Math.round(pct)));
		if (payload?.defaults) defaults = payload.defaults;
		configured = Boolean(payload?.configured);
		pwmSupported = Boolean(payload?.pwm_supported);
		hardwareReady = Boolean(payload?.hardware_ready);
		leds = Array.isArray(payload?.leds) ? payload.leds : [];
	}

	async function loadStatus(showLoading = true) {
		if (showLoading) loading = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/leds`);
			if (!res.ok) throw new Error(await res.text());
			applyStatus(await res.json());
			errorMsg = null;
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to load LED settings.';
		} finally {
			if (showLoading) loading = false;
		}
	}

	async function post(body: Record<string, unknown>) {
		saving = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/leds`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
			if (!res.ok) throw new Error(await res.text());
			applyStatus(await res.json());
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to update LEDs.';
		} finally {
			saving = false;
		}
	}

	function saveEnabled(next: boolean) {
		enabled = next;
		void post({ enabled: next });
	}

	function saveOnAtBoot(next: boolean) {
		onAtBoot = next;
		void post({ on_at_boot: next });
	}

	function saveBrightness(next: number) {
		if (!Number.isFinite(next)) return;
		const clamped = Math.max(0, Math.min(100, Math.round(next)));
		brightnessPercent = clamped;
		if (brightnessTimer) clearTimeout(brightnessTimer);
		brightnessTimer = setTimeout(() => {
			void post({ brightness_percent: clamped });
		}, BRIGHTNESS_DEBOUNCE_MS);
	}

	onMount(() => {
		void loadStatus();
		pollTimer = setInterval(() => void loadStatus(false), STATUS_POLL_MS);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
		if (brightnessTimer) clearTimeout(brightnessTimer);
	});
</script>

<div class="flex flex-col gap-2">
	{#if errorMsg}
		<Alert variant="danger">{errorMsg}</Alert>
	{/if}

	{#if !loading && !configured && hardwareReady}
		<Alert variant="info">
			No LEDs are wired up on this machine. Declare them in <code>machine.toml</code> with a
			<code>[[gpio_leds]]</code> entry per LED (board plus digital-output channel), then restart the backend.
		</Alert>
	{:else if !loading && !hardwareReady}
		<Alert variant="info">
			Machine hardware is not initialized, so the LEDs cannot be driven right now. Changes are saved
			and applied the next time the machine starts up.
		</Alert>
	{:else if !loading && configured && !pwmSupported}
		<Alert variant="warning">
			The control board firmware does not support PWM output, so brightness has no effect — the LEDs
			are either fully on or fully off. Reflash the board from Settings → Versions to enable
			dimming.
		</Alert>
	{/if}

	<SettingRow
		label="LEDs on"
		description="Turns the machine's LED lighting on or off right now. On drives the LEDs at the brightness set below."
		changed={enabled !== defaults.enabled}
		defaultLabel={defaults.enabled ? 'on' : 'off'}
		onRevert={() => saveEnabled(defaults.enabled)}
	>
		<ToggleSwitch
			checked={enabled}
			label="LEDs on"
			disabled={loading || saving}
			onToggle={() => saveEnabled(!enabled)}
		/>
	</SettingRow>

	<SettingRow
		label="Turn LEDs on at startup"
		description="When on, the LEDs light up automatically as soon as the machine finishes initializing its hardware. When off, they stay dark until you switch them on here."
		changed={onAtBoot !== defaults.on_at_boot}
		defaultLabel={defaults.on_at_boot ? 'on' : 'off'}
		onRevert={() => saveOnAtBoot(defaults.on_at_boot)}
	>
		<ToggleSwitch
			checked={onAtBoot}
			label="Turn LEDs on at startup"
			disabled={loading || saving}
			onToggle={() => saveOnAtBoot(!onAtBoot)}
		/>
	</SettingRow>

	<SettingRow
		label="Brightness"
		description="PWM duty cycle driven onto every configured LED output. 100% is full brightness; the LEDs still go fully dark when the toggle above is off."
		changed={brightnessPercent !== defaults.brightness_percent}
		defaultLabel={`${defaults.brightness_percent}%`}
		onRevert={() => saveBrightness(defaults.brightness_percent)}
	>
		<div class="flex items-center gap-3">
			<input
				type="range"
				min="0"
				max="100"
				step="1"
				value={brightnessPercent}
				disabled={loading || !pwmSupported}
				aria-label="LED brightness percent"
				oninput={(e) => saveBrightness(Number(e.currentTarget.value))}
				class="w-40"
			/>
			<span class="w-12 shrink-0 text-right text-sm text-text tabular-nums">
				{brightnessPercent}%
			</span>
		</div>
	</SettingRow>

	{#if leds.length > 0}
		<div class="border border-border bg-bg px-3 py-2.5 text-sm text-text-muted">
			Driving {leds.length} output{leds.length === 1 ? '' : 's'}:
			{#each leds as led, i}
				<span class="text-text">
					{led.board_role} ch{led.channel}{i < leds.length - 1 ? ',' : ''}
				</span>
			{/each}
		</div>
	{/if}
</div>

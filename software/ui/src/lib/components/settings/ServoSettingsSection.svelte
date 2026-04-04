<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type ServoBackend = 'pca9685' | 'waveshare';
	type ServoChannelDraft = {
		id: string;
		invert: boolean;
	};

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let backend = $state<ServoBackend>('pca9685');
	let openAngle = $state(10);
	let closedAngle = $state(83);
	let port = $state('');
	let layerCount = $state(0);
	let channels = $state<ServoChannelDraft[]>([]);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function normalizedChannels(count: number, source: Array<{ id?: number; invert?: boolean }> = []) {
		return Array.from({ length: count }, (_, index) => {
			const existing = source[index];
			return {
				id: typeof existing?.id === 'number' ? String(existing.id) : '',
				invert: Boolean(existing?.invert)
			} satisfies ServoChannelDraft;
		});
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			const servo = payload?.servo ?? {};
			layerCount = Number(servo.layer_count ?? 0);
			backend = servo.backend === 'waveshare' ? 'waveshare' : 'pca9685';
			openAngle = Number(servo.open_angle ?? 10);
			closedAngle = Number(servo.closed_angle ?? 83);
			port = typeof servo.port === 'string' ? servo.port : '';
			channels = normalizedChannels(layerCount, Array.isArray(servo.channels) ? servo.channels : []);
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load bin / servo settings';
		} finally {
			loading = false;
		}
	}

	async function saveSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const parsedChannels =
				backend === 'waveshare'
					? channels.map((channel, index) => {
							const id = Number(channel.id);
							if (!Number.isInteger(id) || id < 1 || id > 253) {
								throw new Error(`Layer ${index + 1} needs a Waveshare servo ID between 1 and 253.`);
							}
							return { id, invert: channel.invert };
						})
					: [];

			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/servo`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					backend,
					open_angle: openAngle,
					closed_angle: closedAngle,
					port: backend === 'waveshare' ? port.trim() || null : null,
					channels: parsedChannels
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			const servo = payload?.settings ?? {};
			layerCount = Number(servo.layer_count ?? layerCount);
			backend = servo.backend === 'waveshare' ? 'waveshare' : 'pca9685';
			openAngle = Number(servo.open_angle ?? openAngle);
			closedAngle = Number(servo.closed_angle ?? closedAngle);
			port = typeof servo.port === 'string' ? servo.port : '';
			channels = normalizedChannels(layerCount, Array.isArray(servo.channels) ? servo.channels : []);
			statusMsg = payload?.message ?? 'Servo settings saved.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save bin / servo settings';
		} finally {
			saving = false;
		}
	}

	function updateChannelId(index: number, value: string) {
		channels = channels.map((channel, channelIndex) =>
			channelIndex === index ? { ...channel, id: value } : channel
		);
	}

	function updateChannelInvert(index: number, invert: boolean) {
		channels = channels.map((channel, channelIndex) =>
			channelIndex === index ? { ...channel, invert } : channel
		);
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
		}
	});
</script>

<div class="flex flex-col gap-4">
	<div class="text-sm text-text-muted">
		Configure the bin-door servo backend. PCA9685 is the default board-driven mode; Waveshare
		uses SC serial bus servos with one servo ID per layer.
	</div>

	<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
		<label class="text-xs text-text">
			Backend
			<select
				bind:value={backend}
				disabled={loading || saving}
				class="mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
			>
				<option value="pca9685">PCA9685</option>
				<option value="waveshare">Waveshare SC</option>
			</select>
		</label>
		<label class="text-xs text-text">
			Open Angle
			<input
				type="number"
				min="0"
				max="180"
				step="1"
				bind:value={openAngle}
				disabled={loading || saving}
				class="mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
		</label>
		<label class="text-xs text-text">
			Closed Angle
			<input
				type="number"
				min="0"
				max="180"
				step="1"
				bind:value={closedAngle}
				disabled={loading || saving}
				class="mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
		</label>
	</div>

	{#if backend === 'waveshare'}
		<div class="flex flex-col gap-3">
			<label class="text-xs text-text">
				Servo Bus Port
				<input
					type="text"
					bind:value={port}
					placeholder="Auto-detect if left blank"
					disabled={loading || saving}
					class="mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>

			<div class="flex flex-col gap-2">
				<div class="text-xs font-medium text-text">Layer Channels</div>
				{#each channels as channel, index}
					<div
						class="grid grid-cols-[minmax(0,1fr)_120px] gap-3 border border-border bg-bg px-3 py-2 sm:grid-cols-[minmax(0,1fr)_120px_110px]"
					>
						<div class="flex items-center text-sm text-text">
							Layer {index + 1}
						</div>
						<label class="text-xs text-text">
							Servo ID
							<input
								type="number"
								min="1"
								max="253"
								step="1"
								value={channel.id}
								oninput={(event) => updateChannelId(index, event.currentTarget.value)}
								disabled={loading || saving}
								class="mt-1 w-full border border-border bg-surface px-2 py-1.5 text-sm text-text"
							/>
						</label>
						<label class="flex items-center gap-2 text-xs text-text">
							<input
								type="checkbox"
								checked={channel.invert}
								onchange={(event) => updateChannelInvert(index, event.currentTarget.checked)}
								disabled={loading || saving}
							/>
							Invert
						</label>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<div class="flex flex-wrap items-center gap-2">
		<button
			onclick={saveSettings}
			disabled={loading || saving}
			class="cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
		>
			{saving ? 'Saving...' : 'Save Bin / Servo Settings'}
		</button>
		<button
			onclick={loadSettings}
			disabled={loading || saving}
			class="cursor-pointer border border-border bg-bg px-3 py-1.5 text-sm text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
		>
			{loading ? 'Loading...' : 'Reload'}
		</button>
	</div>

	{#if errorMsg}
		<div class="text-sm text-[#D01012] dark:text-red-400">{errorMsg}</div>
	{:else if statusMsg}
		<div class="text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>

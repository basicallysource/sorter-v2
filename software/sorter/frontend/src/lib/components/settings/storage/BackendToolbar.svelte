<script lang="ts">
	type ServoBackend = 'pca9685' | 'waveshare';
	type WavesharePort = {
		device: string;
		product: string;
		serial: string | null;
		confirmed?: boolean;
		servo_count?: number;
	};

	let {
		backend = $bindable(),
		openAngle = $bindable(),
		closedAngle = $bindable(),
		port = $bindable(),
		availablePorts,
		portsLoaded,
		loading,
		saving,
		layerCount,
		onSave,
		onReload
	}: {
		backend: ServoBackend;
		openAngle: number;
		closedAngle: number;
		port: string;
		availablePorts: WavesharePort[];
		portsLoaded: boolean;
		loading: boolean;
		saving: boolean;
		layerCount: number;
		onSave: () => void;
		onReload: () => void;
	} = $props();
</script>

<div class="flex flex-wrap items-end gap-3">
	<label class="text-xs text-text">
		Backend
		<select
			bind:value={backend}
			disabled={loading || saving}
			class="mt-1 block w-40 border border-border bg-bg px-2 py-1.5 text-sm text-text"
		>
			<option value="pca9685">PCA9685</option>
			<option value="waveshare">Waveshare SC</option>
		</select>
	</label>

	{#if backend === 'pca9685'}
		<label class="text-xs text-text">
			Open Angle
			<input
				type="number"
				min="0"
				max="180"
				step="1"
				bind:value={openAngle}
				disabled={loading || saving}
				class="mt-1 block w-24 border border-border bg-bg px-2 py-1.5 text-sm text-text"
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
				class="mt-1 block w-24 border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
		</label>
	{:else}
		<label class="min-w-0 flex-1 text-xs text-text">
			Port
			{#if portsLoaded && availablePorts.length > 0}
				<select
					bind:value={port}
					disabled={loading || saving}
					class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				>
					<option value="">Auto-detect</option>
					{#each availablePorts as p}
						<option value={p.device}>{p.device} — {p.product}{p.confirmed ? ` (${p.servo_count} servos)` : ''}</option>
					{/each}
				</select>
			{:else}
				<input
					type="text"
					bind:value={port}
					placeholder="Auto-detect"
					disabled={loading || saving}
					class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			{/if}
		</label>
	{/if}

	<div class="flex items-center gap-2 pb-0.5">
		<button
			onclick={onSave}
			disabled={loading || saving || layerCount === 0}
			class="cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
		>
			{saving ? 'Saving...' : 'Save'}
		</button>
		<button
			onclick={onReload}
			disabled={loading || saving}
			class="cursor-pointer text-xs text-text-muted hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
		>
			{loading ? 'Loading...' : 'Reload'}
		</button>
	</div>
</div>

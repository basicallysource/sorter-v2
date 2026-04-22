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
		saving
	}: {
		backend: ServoBackend;
		openAngle: number;
		closedAngle: number;
		port: string;
		availablePorts: WavesharePort[];
		portsLoaded: boolean;
		loading: boolean;
		saving: boolean;
	} = $props();
</script>

<div class="setup-panel p-4">
	<div class="text-sm font-semibold text-text">Servo backend</div>
	<div class="mt-1 text-sm text-text-muted">
		Pick the controller used for storage-layer servos and the default open/closed angles.
	</div>

	<div class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
		<label class="flex flex-col gap-1 text-sm text-text-muted">
			<span>Backend</span>
			<select
				bind:value={backend}
				disabled={loading || saving}
				class="setup-control px-3 py-2 text-sm text-text"
			>
				<option value="pca9685">PCA9685</option>
				<option value="waveshare">Waveshare SC</option>
			</select>
		</label>

		{#if backend === 'pca9685'}
			<label class="flex flex-col gap-1 text-sm text-text-muted">
				<span>Default open angle (°)</span>
				<input
					type="number"
					min="0"
					max="180"
					step="1"
					bind:value={openAngle}
					disabled={loading || saving}
					class="setup-control px-3 py-2 text-sm text-text"
				/>
			</label>
			<label class="flex flex-col gap-1 text-sm text-text-muted">
				<span>Default closed angle (°)</span>
				<input
					type="number"
					min="0"
					max="180"
					step="1"
					bind:value={closedAngle}
					disabled={loading || saving}
					class="setup-control px-3 py-2 text-sm text-text"
				/>
			</label>
		{:else}
			<label class="flex flex-col gap-1 text-sm text-text-muted sm:col-span-2 lg:col-span-3">
				<span>Serial port</span>
				{#if portsLoaded && availablePorts.length > 0}
					<select
						bind:value={port}
						disabled={loading || saving}
						class="setup-control px-3 py-2 text-sm text-text"
					>
						<option value="">Auto-detect</option>
						{#each availablePorts as p}
							<option value={p.device}
								>{p.device} — {p.product}{p.confirmed
									? ` (${p.servo_count} servos)`
									: ''}</option
							>
						{/each}
					</select>
				{:else}
					<input
						type="text"
						bind:value={port}
						placeholder="Auto-detect"
						disabled={loading || saving}
						class="setup-control px-3 py-2 text-sm text-text"
					/>
				{/if}
			</label>
		{/if}
	</div>
</div>

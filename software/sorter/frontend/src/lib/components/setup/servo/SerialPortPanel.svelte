<script lang="ts">
	type WavesharePort = {
		device: string;
		product: string;
		serial: string | null;
		confirmed?: boolean;
		servo_count?: number;
	};

	let {
		port = $bindable(),
		availablePorts,
		loadingPorts,
		onLoadPorts,
		onScan
	}: {
		port: string;
		availablePorts: WavesharePort[];
		loadingPorts: boolean;
		onLoadPorts: () => void;
		onScan: () => void;
	} = $props();
</script>

<div class="setup-panel p-4">
	<div class="text-sm font-semibold text-text">Serial port</div>
	<div class="mt-3 grid gap-3 sm:grid-cols-[2fr_auto_auto]">
		<select bind:value={port} class="setup-control px-3 py-2 text-text">
			<option value="">Auto detect / current selection</option>
			{#each availablePorts as candidate}
				<option value={candidate.device}>
					{candidate.device} · {candidate.product}
				</option>
			{/each}
		</select>
		<button
			onclick={onLoadPorts}
			disabled={loadingPorts}
			class="setup-button-secondary px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
		>
			{loadingPorts ? 'Refreshing…' : 'Refresh ports'}
		</button>
		<button
			onclick={onScan}
			class="border border-primary bg-primary px-3 py-2 text-sm font-medium text-primary-contrast transition-colors hover:bg-primary-hover"
		>
			Scan bus
		</button>
	</div>
</div>

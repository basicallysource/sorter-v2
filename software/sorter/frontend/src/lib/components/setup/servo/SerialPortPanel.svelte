<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
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

<Panel title="Serial port">
	<div class="flex flex-wrap items-center gap-2">
		<Select
			label="Serial port"
			class="min-w-0 flex-[2_1_16rem]"
			bind:value={port}
			options={[
				{ value: '', label: 'Detect it, or keep the current one' },
				...availablePorts.map((candidate) => ({
					value: candidate.device,
					label: `${candidate.device} · ${candidate.product}`
				}))
			]}
		/>
		<Button loading={loadingPorts} onclick={onLoadPorts}>Refresh the ports</Button>
		<Button variant="primary" onclick={onScan}>Scan the bus</Button>
	</div>
</Panel>

<script lang="ts">
	import { RefreshCcw } from 'lucide-svelte';

	type BusServo = {
		id: number;
		model: number | null;
		model_name: string | null;
		position: number | null;
		load: number | null;
		min_limit: number | null;
		max_limit: number | null;
		voltage: number | null;
		temperature: number | null;
		current: number | null;
		pid: { p: number; d: number; i: number } | null;
		error?: string;
	};

	type WavesharePort = {
		device: string;
		product: string;
		serial: string | null;
		confirmed?: boolean;
		servo_count?: number;
	};

	let {
		busServos,
		busScanning,
		busError,
		busStatusMsg,
		busSuggestedNextId,
		changingIdFor,
		newIdInputs = $bindable(),
		port,
		availablePorts,
		onScan,
		onChangeId
	}: {
		busServos: BusServo[];
		busScanning: boolean;
		busError: string | null;
		busStatusMsg: string;
		busSuggestedNextId: number | null;
		changingIdFor: number | null;
		newIdInputs: Record<number, string>;
		port: string;
		availablePorts: WavesharePort[];
		onScan: () => void;
		onChangeId: (oldId: number) => void;
	} = $props();
</script>

<div class="setup-panel p-4">
	<div class="flex items-start justify-between gap-3">
		<div class="min-w-0 flex-1">
			<div class="text-sm font-semibold text-text">Waveshare bus</div>
			<div class="mt-1 text-sm text-text-muted">
				Detected servo IDs. Use this to reassign a factory-default servo (ID 1) to a unique ID
				before plugging in the next one.
			</div>
		</div>
		<button
			onclick={onScan}
			disabled={busScanning}
			class="setup-button-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-text disabled:cursor-not-allowed disabled:opacity-50"
		>
			<RefreshCcw size={14} class={busScanning ? 'animate-spin' : ''} />
			{busScanning ? 'Scanning…' : 'Scan Bus'}
		</button>
	</div>

	{#if busError}
		<div class="mt-3 text-sm text-danger dark:text-red-400">{busError}</div>
	{:else if busStatusMsg}
		<div class="mt-3 text-sm text-text-muted">{busStatusMsg}</div>
	{/if}

	{#if busServos.length > 0}
		<div class="mt-4 flex flex-col gap-2">
			{#each busServos as servo}
				{@const isFactory = servo.id === 1}
				<div
					class="flex flex-wrap items-center gap-3 border border-border bg-bg px-3 py-2 {isFactory
						? 'border-warning/60'
						: ''}"
				>
					<div
						class="flex h-10 w-14 shrink-0 flex-col items-center justify-center bg-primary font-bold text-primary-contrast"
					>
						<span class="text-xs uppercase tracking-wider opacity-80">ID</span>
						<span class="text-sm leading-none">{servo.id}</span>
					</div>

					<div class="min-w-0 flex-1">
						{#if isFactory}
							<div class="text-sm font-semibold text-warning">Factory default</div>
							<div class="text-sm text-text-muted">
								Assign a unique ID before plugging in the next servo.
							</div>
						{:else}
							<div class="text-sm text-text">Assigned</div>
						{/if}
					</div>

					<div class="flex items-center gap-2">
						<input
							type="number"
							min="1"
							max="253"
							value={newIdInputs[servo.id] ?? ''}
							oninput={(e) => {
								newIdInputs = { ...newIdInputs, [servo.id]: e.currentTarget.value };
							}}
							placeholder={isFactory && busSuggestedNextId
								? String(busSuggestedNextId)
								: 'New ID'}
							disabled={changingIdFor !== null}
							class="setup-control w-24 px-2 py-1.5 text-sm text-text"
						/>
						<button
							onclick={() => onChangeId(servo.id)}
							disabled={changingIdFor !== null || !newIdInputs[servo.id]}
							class="setup-button-secondary px-3 py-1.5 text-sm font-medium text-text disabled:cursor-not-allowed disabled:opacity-50"
						>
							{changingIdFor === servo.id ? 'Setting…' : 'Set ID'}
						</button>
					</div>
				</div>
			{/each}
		</div>
	{:else if !busScanning}
		<div class="mt-3 text-sm text-text-muted">
			{#if !port && availablePorts.length === 0}
				Select a port above and save before scanning, or connect the Waveshare servo board.
			{:else}
				Press "Scan Bus" to detect connected servos.
			{/if}
		</div>
	{/if}
</div>

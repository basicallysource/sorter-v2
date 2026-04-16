<script lang="ts">
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

	function modelLabel(servo: BusServo): string {
		if (servo.model_name) return servo.model_name;
		if (servo.model !== null) return `SC?? (${servo.model})`;
		return '--';
	}
</script>

<div class="mt-6 flex flex-col gap-3">
	<div class="flex items-center gap-3">
		<h3 class="text-sm font-medium text-text">Waveshare Servos on Bus</h3>
		<button
			onclick={onScan}
			disabled={busScanning}
			class="cursor-pointer border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
		>
			{busScanning ? 'Scanning...' : 'Scan Bus'}
		</button>
	</div>

	{#if busError}
		<div class="text-sm text-danger dark:text-red-400">{busError}</div>
	{:else if busStatusMsg}
		<div class="text-sm text-text-muted">{busStatusMsg}</div>
	{/if}

	{#if busServos.length > 0}
		<div class="overflow-hidden border border-border">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-border bg-surface text-left text-xs">
						<th class="px-3 py-2 font-medium text-text-muted">ID</th>
						<th class="px-3 py-2 font-medium text-text-muted">Model</th>
						<th class="px-3 py-2 font-medium text-text-muted">Position</th>
						<th class="px-3 py-2 font-medium text-text-muted">Limits</th>
						<th class="px-3 py-2 font-medium text-text-muted">Temp</th>
						<th class="px-3 py-2 font-medium text-text-muted">Voltage</th>
						<th class="px-3 py-2 font-medium text-text-muted">Load</th>
						<th class="px-3 py-2 font-medium text-text-muted">PID</th>
						<th class="px-3 py-2 text-right font-medium text-text-muted">Change ID</th>
					</tr>
				</thead>
				<tbody>
					{#each busServos as servo}
						<tr class="border-b border-border bg-bg last:border-b-0 {servo.id === 1 ? 'bg-amber-50 dark:bg-amber-950/20' : ''}">
							<td class="px-3 py-2 font-medium text-text">
								{servo.id}
								{#if servo.id === 1}
									<span class="ml-1 text-xs text-amber-600 dark:text-amber-400" title="Factory default ID — assign a unique ID before use">Factory</span>
								{/if}
							</td>
							<td class="px-3 py-2 font-mono text-xs text-text-muted">{modelLabel(servo)}</td>
							<td class="px-3 py-2 font-mono text-xs text-text-muted">{servo.position ?? '--'}</td>
							<td class="px-3 py-2 font-mono text-xs text-text-muted">
								{servo.min_limit ?? '--'} – {servo.max_limit ?? '--'}
							</td>
							<td class="px-3 py-2 font-mono text-xs text-text-muted">
								{servo.temperature !== null && servo.temperature !== undefined ? `${servo.temperature}°C` : '--'}
							</td>
							<td class="px-3 py-2 font-mono text-xs text-text-muted">
								{servo.voltage !== null && servo.voltage !== undefined ? `${servo.voltage}V` : '--'}
							</td>
							<td class="px-3 py-2 font-mono text-xs text-text-muted">
								{servo.load ?? '--'}
							</td>
							<td class="px-3 py-2 font-mono text-xs text-text-muted">
								{#if servo.pid}
									{servo.pid.p}/{servo.pid.d}/{servo.pid.i}
								{:else}
									--
								{/if}
							</td>
							<td class="px-3 py-2 text-right">
								<div class="flex items-center justify-end gap-1.5">
									<input
										type="number"
										min="1"
										max="253"
										value={newIdInputs[servo.id] ?? ''}
										oninput={(e) => {
											newIdInputs = { ...newIdInputs, [servo.id]: e.currentTarget.value };
										}}
										placeholder={servo.id === 1 && busSuggestedNextId ? String(busSuggestedNextId) : 'New ID'}
										disabled={changingIdFor !== null}
										class="w-20 border border-border bg-surface px-1.5 py-1 text-xs text-text"
									/>
									<button
										onclick={() => onChangeId(servo.id)}
										disabled={changingIdFor !== null || !newIdInputs[servo.id]}
										class="cursor-pointer border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
									>
										{changingIdFor === servo.id ? '...' : 'Set'}
									</button>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else if !busScanning}
		<div class="text-xs text-text-muted">
			{#if !port && availablePorts.length === 0}
				Select a port above and save before scanning, or connect the Waveshare servo board.
			{:else}
				Press "Scan Bus" to detect connected servos.
			{/if}
		</div>
	{/if}
</div>

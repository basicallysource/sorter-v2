<script lang="ts">
	let {
		drvStatus
	}: {
		drvStatus: Record<string, any>;
	} = $props();
</script>

{#snippet flag(label: string, on: boolean, tone: 'danger' | 'warning')}
	<div class="flex justify-between gap-2">
		<dt class="text-ink-muted">{label}</dt>
		<dd class={on ? (tone === 'danger' ? 'font-medium text-danger-ink' : 'font-medium text-warning-ink') : 'text-ink'}>
			{on ? 'Yes' : 'No'}
		</dd>
	</div>
{/snippet}

<div class="px-(--pad-panel) py-(--pad-row)">
	<div class="label">Driver status (DRV_STATUS)</div>
	<dl class="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 rounded-control bg-well p-3 text-sm">
		{@render flag('Overheated', drvStatus.ot, 'danger')}
		{@render flag('Heat warning', drvStatus.otpw, 'warning')}
		{@render flag('Short, coil A', drvStatus.s2ga, 'danger')}
		{@render flag('Short, coil B', drvStatus.s2gb, 'danger')}
		{@render flag('Open, coil A', drvStatus.ola, 'warning')}
		{@render flag('Open, coil B', drvStatus.olb, 'warning')}
		<div class="flex justify-between gap-2">
			<dt class="text-ink-muted">StealthChop</dt>
			<dd class="text-ink">{drvStatus.stealth ? 'Active' : 'Off'}</dd>
		</div>
		<div class="flex justify-between gap-2">
			<dt class="text-ink-muted">Standing still</dt>
			<dd class="text-ink">{drvStatus.stst ? 'Yes' : 'No'}</dd>
		</div>
		<div class="flex justify-between gap-2">
			<dt class="text-ink-muted">Current (CS_ACTUAL)</dt>
			<dd class="num text-ink">{drvStatus.cs_actual}</dd>
		</div>
		<div class="flex justify-between gap-2">
			<dt class="text-ink-muted">SG_RESULT</dt>
			<dd class="num text-ink">{drvStatus.sg_result}</dd>
		</div>
		<div
			class="col-span-2 flex justify-between gap-2 {drvStatus.ot
				? 'font-medium text-danger-ink'
				: drvStatus.otpw
					? 'font-medium text-warning-ink'
					: ''}"
		>
			<dt class={drvStatus.ot || drvStatus.otpw ? '' : 'text-ink-muted'}>Temperature</dt>
			<dd class={drvStatus.ot || drvStatus.otpw ? '' : 'text-ink'}>
				{drvStatus.ot
					? 'Above 157 °C, shut down'
					: drvStatus.t157
						? 'Above 157 °C'
						: drvStatus.t150
							? 'Above 150 °C'
							: drvStatus.t143
								? 'Above 143 °C'
								: drvStatus.t120
									? 'Above 120 °C'
									: 'Below 120 °C'}
			</dd>
		</div>
	</dl>
</div>

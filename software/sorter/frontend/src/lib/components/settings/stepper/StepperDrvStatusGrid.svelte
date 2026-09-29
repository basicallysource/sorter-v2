<script lang="ts">
	let {
		drvStatus
	}: {
		drvStatus: Record<string, any>;
	} = $props();
</script>

<div class="flex flex-col gap-1">
	<div class="text-xs text-ink-muted">
		DRV_STATUS
	</div>
	<div class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
		<div class={drvStatus.ot ? 'font-semibold text-danger-ink' : 'text-ink-muted'}>
			Overtemp: {drvStatus.ot ? 'YES' : 'No'}
		</div>
		<div class={drvStatus.otpw ? 'font-semibold text-yellow-500' : 'text-ink-muted'}>
			OT Pre-warn: {drvStatus.otpw ? 'YES' : 'No'}
		</div>
		<div class={drvStatus.s2ga ? 'font-semibold text-danger-ink' : 'text-ink-muted'}>
			Short A: {drvStatus.s2ga ? 'YES' : 'No'}
		</div>
		<div class={drvStatus.s2gb ? 'font-semibold text-danger-ink' : 'text-ink-muted'}>
			Short B: {drvStatus.s2gb ? 'YES' : 'No'}
		</div>
		<div class={drvStatus.ola ? 'font-semibold text-yellow-500' : 'text-ink-muted'}>
			Open A: {drvStatus.ola ? 'YES' : 'No'}
		</div>
		<div class={drvStatus.olb ? 'font-semibold text-yellow-500' : 'text-ink-muted'}>
			Open B: {drvStatus.olb ? 'YES' : 'No'}
		</div>
		<div class="text-ink-muted">
			StealthChop: {drvStatus.stealth ? 'Active' : 'Off'}
		</div>
		<div class="text-ink-muted">
			Standstill: {drvStatus.stst ? 'Yes' : 'No'}
		</div>
		<div class="text-ink-muted">
			CS Actual: {drvStatus.cs_actual}
		</div>
		<div class="text-ink-muted">
			SG Result: {drvStatus.sg_result}
		</div>
		<div
			class="col-span-2 {drvStatus.ot
				? 'font-semibold text-danger-ink'
				: drvStatus.otpw
					? 'font-semibold text-yellow-500'
					: 'text-ink-muted'}"
		>
			Temp: {drvStatus.ot
				? '>157°C SHUTDOWN'
				: drvStatus.t157
					? '>157°C'
					: drvStatus.t150
						? '>150°C'
						: drvStatus.t143
							? '>143°C'
							: drvStatus.t120
								? '>120°C'
								: '<120°C'}
		</div>
	</div>
</div>

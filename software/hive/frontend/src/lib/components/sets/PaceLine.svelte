<script lang="ts">
	let {
		ratePerHour,
		etaHours,
		plateau,
		found,
		needed
	}: {
		ratePerHour: number | null;
		etaHours: number | null;
		plateau: boolean;
		found: number;
		needed: number;
	} = $props();

	const missing = $derived(Math.max(0, needed - found));

	function hours(value: number): string {
		if (value < 1) return `${Math.max(1, Math.round(value * 60))} min`;
		if (value < 48) return `~${value.toFixed(value < 10 ? 1 : 0)} h`;
		return `~${Math.round(value / 24)} d`;
	}
</script>

{#if plateau}
	<p class="mt-1 text-xs text-warning-strong" title="Under one part per hour for the last hour: this pile has nothing more for the set.">
		Plateau · nothing more from this pile · {missing} missing
	</p>
{:else if ratePerHour !== null}
	<p class="mt-1 text-xs text-text-muted" title="Rate over the last hour; the time to 90 % assumes it holds. The last 10 % are usually a reorder.">
		{ratePerHour} parts/h
		{#if etaHours === 0}
			· 90 % reached
		{:else if etaHours !== null}
			· {hours(etaHours)} to 90 % at this rate
		{/if}
	</p>
{:else}
	<p class="mt-1 text-xs text-text-muted">Pace after the first hour of sorting</p>
{/if}

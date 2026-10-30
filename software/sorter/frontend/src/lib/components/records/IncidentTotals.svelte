<script lang="ts">
	import Panel from '$lib/components/ui/Panel.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import { formatKind, type IncidentsSummary } from './incidents';

	// The incident numbers in one row: how many, how many are open, and which
	// kind is most frequent.
	let { summary }: { summary: IncidentsSummary } = $props();
</script>

<Panel flush>
	<div class="grid grid-cols-2 gap-px bg-line sm:grid-cols-4">
		<div class="bg-surface">
			<Stat label="Total incidents" value={summary.total.toLocaleString()} />
		</div>
		<div class="bg-surface">
			<Stat
				label="Currently active"
				value={summary.active.toLocaleString()}
				hint={summary.active > 0 ? 'awaiting the operator' : undefined}
				tone={summary.active > 0 ? 'warning' : undefined}
			/>
		</div>
		<div class="bg-surface">
			<Stat label="Distinct kinds" value={summary.by_kind.length.toLocaleString()} />
		</div>
		<div class="bg-surface">
			<Stat
				label="Most frequent"
				value={summary.by_kind[0] ? formatKind(summary.by_kind[0].kind) : '—'}
				hint={summary.by_kind[0] ? `${summary.by_kind[0].count.toLocaleString()} times` : undefined}
			/>
		</div>
	</div>
</Panel>

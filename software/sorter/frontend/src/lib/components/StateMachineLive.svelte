<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';

	type MachineStateStats = {
		current_state?: string;
		entered_at?: number;
	};

	const ctx = getMachineContext();
	const runtime_stats = $derived((ctx.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const state_machines = $derived(
		(runtime_stats.state_machines ?? {}) as Record<string, MachineStateStats>
	);
	const now_s = $derived.by(() => Date.now() / 1000.0);

	const preferred_order = [
		'distribution',
		'distribution.occupancy',
		'classification',
		'classification.occupancy',
		'feeder',
		'feeder.ch3',
		'feeder.ch2',
		'feeder.ch1'
	];

	const ordered_machine_names = $derived.by(() => {
		const names = new Set(Object.keys(state_machines));
		const ordered: string[] = [];
		for (const preferred of preferred_order) {
			if (names.has(preferred)) {
				ordered.push(preferred);
				names.delete(preferred);
			}
		}
		for (const remaining of Array.from(names).sort()) {
			ordered.push(remaining);
		}
		return ordered;
	});

	function friendlyName(machineName: string): string {
		const mapping: Record<string, string> = {
			distribution: 'Distribution',
			'distribution.occupancy': 'Distribution Lane',
			classification: 'Classification',
			'classification.occupancy': 'Classification Lane',
			feeder: 'Feeder',
			'feeder.ch1': 'C1 Bulk',
			'feeder.ch2': 'C2 Separation',
			'feeder.ch3': 'C3 Precise'
		};
		return mapping[machineName] ?? machineName.replaceAll('.', ' / ');
	}

	function formatElapsed(enteredAt: number | undefined, now: number): string {
		if (typeof enteredAt !== 'number') return '-';
		const elapsed = Math.max(0, now - enteredAt);
		if (elapsed < 10) return `${elapsed.toFixed(1)}s`;
		if (elapsed < 60) return `${elapsed.toFixed(0)}s`;
		if (elapsed < 3600) return `${(elapsed / 60).toFixed(1)}m`;
		return `${(elapsed / 3600).toFixed(1)}h`;
	}

	function stateTone(stateName: string | undefined): string {
		const normalized = (stateName ?? '').toLowerCase();
		if (
			normalized.includes('recover') ||
			normalized.includes('stalled') ||
			normalized.includes('error') ||
			normalized.includes('jam')
		) {
			return 'text-danger';
		}
		if (
			normalized.includes('wait') ||
			normalized.includes('blocked') ||
			normalized.includes('held')
		) {
			return 'text-warning-dark';
		}
		return 'text-success-dark';
	}
</script>

<div class="setup-card-shell flex h-full min-h-0 flex-col border">
	<div class="setup-card-header flex items-center justify-between px-3 py-2 text-sm font-medium text-text">
		<span>Live States</span>
		<span class="text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">
			{ordered_machine_names.length} active
		</span>
	</div>

	<div class="min-h-0 flex-1 overflow-y-auto p-2">
		{#if ordered_machine_names.length === 0}
			<div class="px-1 py-3 text-sm text-text-muted">No state machines yet</div>
		{:else}
			<div class="space-y-1">
				{#each ordered_machine_names as machine_name}
					{@const data = state_machines[machine_name] ?? {}}
					<div class="rounded border border-border/60 bg-surface px-3 py-2">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0">
								<div class="truncate text-[11px] uppercase tracking-[0.14em] text-text-muted">
									{friendlyName(machine_name)}
								</div>
								<div class={`truncate text-sm font-semibold ${stateTone(data.current_state)}`}>
									{data.current_state ?? 'unknown'}
								</div>
							</div>
							<div class="shrink-0 text-right text-[11px] text-text-muted">
								since {formatElapsed(data.entered_at, now_s)}
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

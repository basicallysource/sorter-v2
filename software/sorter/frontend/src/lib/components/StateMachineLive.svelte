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
			return 'text-danger-ink';
		}
		if (
			normalized.includes('wait') ||
			normalized.includes('blocked') ||
			normalized.includes('held')
		) {
			return 'text-warning-ink';
		}
		return 'text-success-ink';
	}
</script>

<div class="h-full overflow-y-auto">
	{#if ordered_machine_names.length === 0}
		<p class="px-4 py-8 text-center text-sm text-ink-muted">No state machines yet</p>
	{:else}
		<p class="px-4 pt-3 text-sm text-ink-muted">
			<span class="num">{ordered_machine_names.length}</span> active
		</p>
		<ul class="divide-y divide-line">
			{#each ordered_machine_names as machine_name}
				{@const data = state_machines[machine_name] ?? {}}
				<li class="flex items-start justify-between gap-3 px-4 py-2.5">
					<div class="min-w-0">
						<div class="truncate text-sm text-ink-muted">{friendlyName(machine_name)}</div>
						<div class="truncate text-sm font-medium {stateTone(data.current_state)}">
							{data.current_state ?? 'unknown'}
						</div>
					</div>
					<div class="num shrink-0 text-right text-sm text-ink-muted">
						Since {formatElapsed(data.entered_at, now_s)}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</div>

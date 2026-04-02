<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { LayoutDashboard, Copy, Check } from 'lucide-svelte';

	let just_copied = $state(false);

	async function copyStats() {
		if (!ctx.machine?.runtimeStats) return;
		await navigator.clipboard.writeText(JSON.stringify(ctx.machine.runtimeStats, null, 2));
		just_copied = true;
		setTimeout(() => (just_copied = false), 1500);
	}

	type Summary = {
		n?: number;
		avg_s?: number;
		med_s?: number;
		p90_s?: number;
		min_s?: number;
		max_s?: number;
	};

	type ThroughputSummary = {
		n?: number;
		avg?: number;
		med?: number;
		p90?: number;
		min?: number;
		max?: number;
	};

	const ctx = getMachineContext();
	const runtime_stats = $derived((ctx.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const counts = $derived((runtime_stats.counts ?? {}) as Record<string, unknown>);
	const timings = $derived((runtime_stats.timings ?? {}) as Record<string, Summary>);
	const throughput = $derived((runtime_stats.throughput ?? {}) as Record<string, unknown>);
	const inter_piece_ppm = $derived((throughput.inter_piece_ppm ?? {}) as ThroughputSummary);
	const feeder = $derived((runtime_stats.feeder ?? {}) as Record<string, unknown>);
	const pulse_counts = $derived((feeder.pulse_counts ?? {}) as Record<string, Record<string, number>>);
	const state_machines = $derived(
		(runtime_stats.state_machines ?? {}) as Record<
			string,
			{
				current_state?: string;
				state_share_pct?: Record<string, number>;
			}
		>
	);
	const blocked_reasons = $derived(
		(runtime_stats.blocked_reason_counts ?? {}) as Record<string, number>
	);
	const updated_at = $derived(typeof runtime_stats.updated_at === 'number' ? runtime_stats.updated_at : null);

	function fmtTime(summary: Summary | undefined): string {
		if (!summary || !summary.n) return '-';
		const avg = summary.avg_s ?? 0;
		const med = summary.med_s ?? 0;
		const p90 = summary.p90_s ?? 0;
		return `${avg.toFixed(2)} / ${med.toFixed(2)} / ${p90.toFixed(2)}`;
	}

	function fmtCount(value: unknown): string {
		return typeof value === 'number' ? `${value}` : '-';
	}

	function fmtDuration(value: unknown): string {
		if (typeof value !== 'number') return '-';
		if (value < 60) return `${value.toFixed(1)}s`;
		if (value < 3600) return `${(value / 60).toFixed(1)}m`;
		return `${(value / 3600).toFixed(1)}h`;
	}

	function fmtPpm(value: unknown): string {
		return typeof value === 'number' ? value.toFixed(2) : '-';
	}

	function fmtPpmSummary(summary: ThroughputSummary | undefined): string {
		if (!summary || !summary.n) return '-';
		const avg = summary.avg ?? 0;
		const med = summary.med ?? 0;
		const p90 = summary.p90 ?? 0;
		return `${avg.toFixed(2)} / ${med.toFixed(2)} / ${p90.toFixed(2)}`;
	}

	function machineGroup(machine_name: string): string {
		if (machine_name.startsWith('feeder.')) return 'feeder';
		if (machine_name.startsWith('classification.')) return 'classification';
		if (machine_name.startsWith('distribution.')) return 'distribution';
		return 'other';
	}

	function stateColor(machine_name: string, state_name: string): string {
		const group_offsets: Record<string, number> = {
			feeder: 0,
			classification: 120,
			distribution: 240,
			other: 60
		};
		const base_offset = group_offsets[machineGroup(machine_name)] ?? group_offsets.other;
		let hash = 0;
		const key = `${machine_name}::${state_name}`;
		for (let i = 0; i < key.length; i += 1) {
			hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
		}
		const slot = hash % 16;
		const hue = (base_offset + slot * 23) % 360;
		const sat = 58 + (slot % 3) * 4;
		const light = slot % 2 === 0 ? 56 : 62;
		return `hsl(${hue} ${sat}% ${light}%)`;
	}
</script>

<div
	class="flex h-full flex-col border border-border bg-surface"
>
	<div
		class="flex items-center justify-between border-b border-border px-3 py-2 text-sm font-medium text-text"
	>
		<span>Runtime Stats</span>
		<div class="flex items-center gap-2">
			<button
				onclick={copyStats}
				class="text-text-muted transition-colors"
				title="Copy as JSON"
			>
				{#if just_copied}
					<Check size={12} />
				{:else}
					<Copy size={12} />
				{/if}
			</button>
			<a
				href="/dashboard/runtime"
				class="flex items-center gap-1 text-[11px] font-normal text-text-muted transition-colors"
				title="Dashboard"
			>
				<LayoutDashboard size={12} />
				<span>Dashboard</span>
			</a>
		</div>
	</div>
	<div class="flex-1 overflow-y-auto p-2 text-xs font-mono">
		{#if !ctx.machine || !ctx.machine.runtimeStats}
			<div class="text-text-muted">No runtime stats yet</div>
		{:else}
			{#if updated_at}
				<div class="mb-2 text-[10px] text-text-muted">
					Updated {new Date(updated_at * 1000).toLocaleTimeString()}
				</div>
			{/if}

			<!-- Counts -->
			<div class="mb-3">
				<div class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text">Counts</div>
				<table class="w-full">
					<tbody>
						<tr class="text-text-muted">
							<td class="pr-3">Seen</td>
							<td class="text-right tabular-nums">{fmtCount(counts.pieces_seen)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-3">Classified</td>
							<td class="text-right tabular-nums">{fmtCount(counts.classified)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-3">Unknown</td>
							<td class="text-right tabular-nums">{fmtCount(counts.unknown)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-3">Not found</td>
							<td class="text-right tabular-nums">{fmtCount(counts.not_found)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-3">Multi drop fail</td>
							<td class="text-right tabular-nums">{fmtCount(counts.multi_drop_fail)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-3">Distributed</td>
							<td class="text-right tabular-nums">{fmtCount(counts.distributed)}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div class="mb-3 border-t border-border pt-3">
				<div class="mb-1 flex items-baseline justify-between text-[11px] font-semibold uppercase tracking-wide text-text">
					<span>Throughput</span>
					<span class="text-[9px] font-normal normal-case tracking-normal text-text-muted">ppm</span>
				</div>
				<table class="w-full">
					<tbody>
						<tr class="text-text-muted">
							<td class="pr-2">overall (running)</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtPpm(throughput.overall_ppm)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-2">inter-piece avg / med / p90</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtPpmSummary(inter_piece_ppm)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-2">running time</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtDuration(throughput.running_time_s)}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Timings -->
			<div class="mb-3 border-t border-border pt-3">
				<div class="mb-1 flex items-baseline justify-between text-[11px] font-semibold uppercase tracking-wide text-text">
					<span>Carousel</span>
					<span class="text-[9px] font-normal normal-case tracking-normal text-text-muted">avg / med / p90 (s)</span>
				</div>
				<table class="w-full">
					<tbody>
						<tr class="text-text-muted">
							<td class="pr-2">found→rotated</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.found_to_rotated_s)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-2">found→next rdy</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.found_to_next_ready_s)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-2">snap window</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.snap_window_s)}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div class="mb-3 border-t border-border pt-3">
				<div class="mb-1 flex items-baseline justify-between text-[11px] font-semibold uppercase tracking-wide text-text">
					<span>Distribution</span>
					<span class="text-[9px] font-normal normal-case tracking-normal text-text-muted">avg / med / p90 (s)</span>
				</div>
				<table class="w-full">
					<tbody>
						<tr class="text-text-muted">
							<td class="pr-2">target→positioned</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.target_selected_to_positioned_s)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-2">motion→positioned</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.motion_started_to_positioned_s)}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- State Machines -->
			<div class="mb-3 border-t border-border pt-3">
				<div class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text">States</div>
				{#if Object.keys(state_machines).length === 0}
					<div class="text-text-muted">-</div>
				{:else}
					{#each Object.entries(state_machines) as [machine_name, machine_data]}
						<div class="mb-1.5">
							<div class="flex items-baseline justify-between text-text">
								<span>{machine_name}</span>
								<span class="text-[10px] text-text-muted">{machine_data.current_state ?? '-'}</span>
							</div>
							{#if machine_data.state_share_pct}
								<div class="mt-0.5 flex h-1.5 overflow-hidden rounded-sm">
									{#each Object.entries(machine_data.state_share_pct) as [state_name, share]}
										<div
											class="h-full"
											title={`${state_name}: ${share.toFixed(1)}%`}
											style="width: {share}%; background: {stateColor(machine_name, state_name)};"
										></div>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				{/if}
			</div>

			<!-- C-Channels -->
			<div class="mb-3 border-t border-border pt-3">
				<div class="mb-1 flex items-baseline justify-between text-[11px] font-semibold uppercase tracking-wide text-text">
					<span>C-Channels</span>
					<span class="text-[9px] font-normal normal-case tracking-normal text-text-muted">avg / med / p90 (s)</span>
				</div>
				<table class="w-full">
					<tbody>
						<tr class="text-text-muted">
							<td class="pr-2">ch2 clr→ch1 pulse</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.ch2_clear_to_ch1_pulse_s)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-2">ch3 clr→ch2 pulse</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.ch3_clear_to_ch2_pulse_s)}</td>
						</tr>
						<tr class="text-text-muted">
							<td class="pr-2">ch3 precise held</td>
							<td class="text-right tabular-nums whitespace-nowrap">{fmtTime(timings.ch3_precise_held_s)}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Pulse Counts -->
			{#if Object.keys(pulse_counts).length > 0}
				<div class="mb-3 border-t border-border pt-3">
					<div class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text">Pulses</div>
					<table class="w-full">
						<thead>
							<tr class="text-[10px] text-text-muted">
								<th class="text-left font-normal"></th>
								<th class="text-right font-normal">sent</th>
								<th class="text-right font-normal">busy</th>
								<th class="text-right font-normal">fail</th>
							</tr>
						</thead>
						<tbody>
							{#each Object.entries(pulse_counts) as [label, c]}
								<tr class="text-text-muted">
									<td class="pr-2">{label}</td>
									<td class="text-right tabular-nums">{c.sent ?? 0}</td>
									<td class="text-right tabular-nums">{c.busy_skip ?? 0}</td>
									<td class="text-right tabular-nums">{c.failed ?? 0}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}

			<!-- Blocked Reasons -->
			{#if Object.keys(blocked_reasons).length > 0}
				<div class="border-t border-border pt-3">
					<div class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text">Blocked</div>
					<table class="w-full">
						<tbody>
							{#each Object.entries(blocked_reasons) as [reason, count]}
								<tr class="text-text-muted">
									<td class="pr-3">{reason}</td>
									<td class="text-right tabular-nums">{count}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{/if}
	</div>
</div>

<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';

	type BusMessage = {
		type?: string;
		recorded_at_wall?: number;
		station?: string;
		open?: boolean;
		reason?: string | null;
		source?: string;
		target?: string;
		in_progress?: boolean;
		target_bin?: unknown;
	};

	const ctx = getMachineContext();
	const runtime_stats = $derived((ctx.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const bus_recent = $derived((runtime_stats.bus_recent ?? []) as BusMessage[]);

	const newest_first = $derived.by(() => [...bus_recent].reverse());

	function formatClock(ts: number | undefined): string {
		if (typeof ts !== 'number') return '--:--:--';
		return new Date(ts * 1000).toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
		});
	}

	function describe(message: BusMessage): string {
		switch (message.type) {
			case 'StationGate':
				return `${message.station} ${message.open ? 'open' : 'busy'}${message.reason ? ` (${message.reason})` : ''}`;
			case 'PieceRequest':
				return `${message.source} requests piece from ${message.target}`;
			case 'PieceDelivered':
				return `${message.source} delivered to ${message.target}`;
			case 'ChuteMotion':
				return message.in_progress ? 'chute moving' : 'chute stopped';
			default:
				return message.type ?? 'message';
		}
	}

	function tagTone(type: string | undefined): string {
		switch (type) {
			case 'StationGate':
				return 'border-primary/30 bg-primary/10 text-primary';
			case 'PieceRequest':
				return 'border-success/30 bg-success/10 text-success-dark';
			case 'PieceDelivered':
				return 'border-success/30 bg-success/10 text-success-dark';
			case 'ChuteMotion':
				return 'border-warning/30 bg-warning/10 text-warning-dark';
			default:
				return 'border-border bg-bg text-text-muted';
		}
	}
</script>

<div class="setup-card-shell flex h-full min-h-0 flex-col border">
	<div class="setup-card-header flex items-center justify-between px-3 py-2 text-sm font-medium text-text">
		<span>Bus Ticker</span>
		<span class="text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">
			{bus_recent.length} recent
		</span>
	</div>

	<div class="min-h-0 flex-1 overflow-y-auto p-2">
		{#if newest_first.length === 0}
			<div class="px-1 py-3 text-sm text-text-muted">No bus traffic yet</div>
		{:else}
			<div class="space-y-1.5">
				{#each newest_first as message}
					<div class="rounded border border-border/60 bg-surface px-3 py-2">
						<div class="mb-1 flex items-center justify-between gap-2">
							<span class={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${tagTone(message.type)}`}>
								{message.type ?? 'message'}
							</span>
							<span class="text-[11px] text-text-muted">
								{formatClock(message.recorded_at_wall)}
							</span>
						</div>
						<div class="text-sm text-text">
							{describe(message)}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

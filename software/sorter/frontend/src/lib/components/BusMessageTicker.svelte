<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
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

	function tagTone(type: string | undefined): 'primary' | 'success' | 'warning' | 'neutral' {
		switch (type) {
			case 'StationGate':
				return 'primary';
			case 'PieceRequest':
			case 'PieceDelivered':
				return 'success';
			case 'ChuteMotion':
				return 'warning';
			default:
				return 'neutral';
		}
	}
</script>

<div class="h-full overflow-y-auto">
	{#if newest_first.length === 0}
		<p class="px-4 py-8 text-center text-sm text-ink-muted">No bus traffic yet</p>
	{:else}
		<p class="px-4 pt-3 text-sm text-ink-muted"><span class="num">{bus_recent.length}</span> recent</p>
		<ul class="divide-y divide-line">
			{#each newest_first as message}
				<li class="px-4 py-2.5">
					<div class="mb-1 flex items-center justify-between gap-2">
						<Badge tone={tagTone(message.type)}>{message.type ?? 'Message'}</Badge>
						<span class="num text-sm text-ink-muted">{formatClock(message.recorded_at_wall)}</span>
					</div>
					<div class="text-sm text-ink">{describe(message)}</div>
				</li>
			{/each}
		</ul>
	{/if}
</div>

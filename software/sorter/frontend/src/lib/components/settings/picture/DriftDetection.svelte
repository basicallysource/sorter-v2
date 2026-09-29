<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import Modal from '$lib/components/Modal.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import type { CameraRole } from '$lib/settings/stations';

	type Diff = {
		key: string;
		saved: number | boolean;
		live: number | boolean;
		kind: 'number' | 'boolean';
	};

	type DiffResponse = {
		ok: boolean;
		role: string;
		source?: number | string | null;
		supported: boolean;
		saved: Record<string, number | boolean>;
		live: Record<string, number | boolean>;
		diffs: Diff[];
		message?: string;
	};

	let {
		role,
		pollMs = 10000,
		onAction
	}: {
		role: CameraRole;
		pollMs?: number;
		onAction?: (action: 'adopt' | 'restore') => void;
	} = $props();

	let open = $state(false);
	let loading = $state(false);
	let applying = $state(false);
	let error = $state<string | null>(null);
	let status = $state('');
	let diffs = $state<Diff[]>([]);
	let savedSnapshot = $state<Record<string, number | boolean>>({});
	let liveSnapshot = $state<Record<string, number | boolean>>({});
	let ignoredSignature = $state<string | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	function signature(ds: Diff[]): string {
		return ds
			.map((d) => `${d.key}:${d.saved}->${d.live}`)
			.sort()
			.join('|');
	}

	function formatValue(v: number | boolean): string {
		if (typeof v === 'boolean') return v ? 'on' : 'off';
		if (Number.isInteger(v)) return String(v);
		return v.toFixed(2);
	}

	async function check(): Promise<void> {
		if (applying || open) return;
		loading = true;
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/cameras/device-settings/${role}/diff`,
				{ cache: 'no-store' }
			);
			if (!res.ok) return;
			const data = (await res.json()) as DiffResponse;
			if (!data.supported) return;
			diffs = data.diffs ?? [];
			savedSnapshot = data.saved ?? {};
			liveSnapshot = data.live ?? {};
			const sig = signature(diffs);
			if (diffs.length > 0 && sig !== ignoredSignature) {
				open = true;
				error = null;
				status = '';
			}
		} catch {
			// swallow — drift check is best-effort
		} finally {
			loading = false;
		}
	}

	async function adopt(): Promise<void> {
		applying = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/device-settings/${role}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(liveSnapshot)
			});
			if (!res.ok) throw new Error(await res.text());
			status = 'Live values saved.';
			open = false;
			ignoredSignature = null;
			onAction?.('adopt');
		} catch (e: any) {
			error = e.message ?? 'Failed to adopt live values';
		} finally {
			applying = false;
		}
	}

	async function restore(): Promise<void> {
		applying = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/device-settings/${role}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(savedSnapshot)
			});
			if (!res.ok) throw new Error(await res.text());
			status = 'Saved settings restored.';
			open = false;
			ignoredSignature = null;
			onAction?.('restore');
		} catch (e: any) {
			error = e.message ?? 'Failed to restore saved values';
		} finally {
			applying = false;
		}
	}

	function ignore(): void {
		ignoredSignature = signature(diffs);
		open = false;
	}

	$effect(() => {
		void role;
		void pollMs;
		if (timer !== null) {
			clearInterval(timer);
			timer = null;
		}
		void check();
		timer = setInterval(() => {
			void check();
		}, pollMs);
		return () => {
			if (timer !== null) {
				clearInterval(timer);
				timer = null;
			}
		};
	});
</script>

<Modal bind:open title="Camera settings drifted">
	<div class="flex flex-col gap-3">
		<p class="text-sm text-ink">
			The camera is reporting different values than what's saved. What should happen?
		</p>

		{#if error}
			<Alert tone="danger">
				<div class="text-sm text-ink">{error}</div>
			</Alert>
		{/if}

		<div class="border border-line">
			<table class="w-full text-sm">
				<thead class="bg-surface text-xs font-semibold text-ink-muted">
					<tr>
						<th class="px-3 py-2 text-left">Setting</th>
						<th class="px-3 py-2 text-right">Saved</th>
						<th class="px-3 py-2 text-right">Live</th>
					</tr>
				</thead>
				<tbody>
					{#each diffs as diff}
						<tr class="border-t border-line">
							<td class="px-3 py-2 font-medium text-ink">{diff.key}</td>
							<td class="px-3 py-2 text-right font-mono text-ink">{formatValue(diff.saved)}</td>
							<td class="px-3 py-2 text-right font-mono text-warning-ink">{formatValue(diff.live)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div class="flex flex-col gap-2 sm:flex-row sm:justify-end">
			<button
				onclick={ignore}
				disabled={applying}
				class="inline-flex items-center justify-center border border-line bg-well px-4 py-2 text-sm text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				Ignore
			</button>
			<button
				onclick={adopt}
				disabled={applying}
				class="inline-flex items-center justify-center border border-primary bg-primary px-4 py-2 text-sm font-medium text-on-primary transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
			>
				Adopt live
			</button>
			<button
				onclick={restore}
				disabled={applying}
				class="inline-flex items-center justify-center border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-50"
			>
				Restore saved
			</button>
		</div>

		{#if status}
			<div class="text-sm text-ink-muted">{status}</div>
		{/if}
	</div>
</Modal>

<script lang="ts">
	import { backendHttpBaseUrl } from '$lib/backend';
	import Modal from '$lib/components/Modal.svelte';
	import { Alert } from '$lib/components/primitives';
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
				`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/diff`,
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
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/device-settings/${role}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(liveSnapshot)
			});
			if (!res.ok) throw new Error(await res.text());
			status = 'Live-Einstellungen als gespeichert übernommen.';
			open = false;
			ignoredSignature = null;
			onAction?.('adopt');
		} catch (e: any) {
			error = e.message ?? 'Übernahme fehlgeschlagen';
		} finally {
			applying = false;
		}
	}

	async function restore(): Promise<void> {
		applying = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/device-settings/${role}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(savedSnapshot)
			});
			if (!res.ok) throw new Error(await res.text());
			status = 'Gespeicherte Einstellungen wiederhergestellt.';
			open = false;
			ignoredSignature = null;
			onAction?.('restore');
		} catch (e: any) {
			error = e.message ?? 'Wiederherstellung fehlgeschlagen';
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

<Modal bind:open title="Kameraeinstellungen abweichend">
	<div class="flex flex-col gap-3">
		<p class="text-sm text-text">
			Die Kamera meldet andere Werte als gespeichert. Was soll passieren?
		</p>

		{#if error}
			<Alert variant="danger">
				<div class="text-sm text-text">{error}</div>
			</Alert>
		{/if}

		<div class="border border-border">
			<table class="w-full text-sm">
				<thead class="bg-surface text-xs font-semibold tracking-wider text-text-muted uppercase">
					<tr>
						<th class="px-3 py-2 text-left">Einstellung</th>
						<th class="px-3 py-2 text-right">Gespeichert</th>
						<th class="px-3 py-2 text-right">Live</th>
					</tr>
				</thead>
				<tbody>
					{#each diffs as diff}
						<tr class="border-t border-border">
							<td class="px-3 py-2 font-medium text-text">{diff.key}</td>
							<td class="px-3 py-2 text-right font-mono text-text">{formatValue(diff.saved)}</td>
							<td class="px-3 py-2 text-right font-mono text-warning-dark">{formatValue(diff.live)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div class="flex flex-col gap-2 sm:flex-row sm:justify-end">
			<button
				onclick={ignore}
				disabled={applying}
				class="inline-flex items-center justify-center border border-border bg-bg px-4 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				Ignorieren
			</button>
			<button
				onclick={adopt}
				disabled={applying}
				class="inline-flex items-center justify-center border border-primary bg-primary px-4 py-2 text-sm font-medium text-primary-contrast transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
			>
				Live übernehmen
			</button>
			<button
				onclick={restore}
				disabled={applying}
				class="inline-flex items-center justify-center border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-50"
			>
				Gespeicherte wiederherstellen
			</button>
		</div>

		{#if status}
			<div class="text-sm text-text-muted">{status}</div>
		{/if}
	</div>
</Modal>

<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	// Per-piece fill units for volume-aware bin limits: 1.0 is the reference
	// piece (a 2x4 brick). Parts without an entry count as the default, so the
	// table only needs the parts whose size differs from it.

	type VolumeRow = { partId: string; units: string; saved: boolean };

	const manager = getMachinesContext();

	let loadedBase = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let defaultUnits = $state('1');
	let rows = $state<VolumeRow[]>([]);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function configChanged(): boolean {
		// Dirty tracking against what the backend last reported: any edited value
		// diverging from its saved state (new rows start unsaved) marks the form.
		return rows.some((row) => !row.saved);
	}

	async function loadConfig() {
		loading = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/bins/fill-config`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			defaultUnits = typeof payload.default_units === 'number' ? String(payload.default_units) : '1';
			const parts: Record<string, number> = payload.parts ?? {};
			rows = Object.entries(parts).map(([partId, units]) => ({
				partId,
				units: String(units),
				saved: true
			}));
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load the piece volumes';
		} finally {
			loading = false;
		}
	}

	function addRow() {
		rows = [...rows, { partId: '', units: '1', saved: false }];
	}

	function removeRow(index: number) {
		rows = rows.filter((_, i) => i !== index);
	}

	function setRow(index: number, patch: Partial<VolumeRow>) {
		rows = rows.map((row, i) => (i === index ? { ...row, ...patch, saved: false } : row));
	}

	async function saveConfig() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const defaultParsed = Number(defaultUnits.trim());
			if (!Number.isFinite(defaultParsed) || defaultParsed <= 0) {
				throw new Error('The default fill value must be a number above 0.');
			}
			const parts: Record<string, number> = {};
			for (const row of rows) {
				const partId = row.partId.trim();
				if (!partId) continue;
				const units = Number(row.units.trim());
				if (!Number.isFinite(units) || units <= 0) {
					throw new Error(`The fill value for ${partId} must be a number above 0.`);
				}
				if (partId in parts) {
					throw new Error(`${partId} appears twice.`);
				}
				parts[partId] = units;
			}
			const res = await fetch(`${currentBackendBaseUrl()}/api/bins/fill-config`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ default_units: defaultParsed, parts })
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			statusMsg = 'Piece volumes saved. Bins already holding pieces are re-valued right away.';
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save the piece volumes';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		const base = currentBackendBaseUrl();
		if (base !== loadedBase) {
			loadedBase = base;
			void loadConfig();
		}
	});
</script>

<Panel title="Piece volumes" description="How much space one piece takes in a bin, in relative fill units (a 2x4 brick is 1).">
	{#snippet actions()}
		<Button size="sm" icon={Plus} disabled={loading || saving} onclick={addRow}>Add a part</Button>
	{/snippet}

	<p class="text-sm text-ink-muted">
		Bins track their contents by volume once a layer has a fill limit: a bin full of 2x1 plates
		holds far more pieces than one full of big panels. Every part not listed here counts as the
		default. Only the ratios matter — tune them as you watch the bins fill.
	</p>

	{#if loading && rows.length === 0}
		<div class="flex items-center gap-2 py-2 text-sm text-ink-muted">
			<Spinner size={14} /> Loading the piece volumes
		</div>
	{:else}
		<div class="flex flex-col gap-3">
			<div class="flex flex-wrap items-end gap-x-4 gap-y-3">
				<Field
					label="Default"
					for="fill-default-units"
					info="The fill value every piece without its own entry counts as."
				>
					<div class="w-24">
						<Input
							id="fill-default-units"
							type="number"
							size="sm"
							min={0.1}
							step={0.1}
							value={defaultUnits}
							disabled={loading || saving}
							oninput={(e) => (defaultUnits = (e.currentTarget as HTMLInputElement).value)}
						/>
					</div>
				</Field>
			</div>
			<div class="flex flex-col gap-2">
				{#each rows as row, index (index)}
					<div class="flex flex-wrap items-center gap-2">
						<div class="w-40">
							<Input
								size="sm"
								placeholder="Part id, e.g. 3001"
								value={row.partId}
								disabled={loading || saving}
								oninput={(e) => setRow(index, { partId: (e.currentTarget as HTMLInputElement).value })}
								aria-label="Part id"
							/>
						</div>
						<div class="w-24">
							<Input
								type="number"
								size="sm"
								min={0.1}
								step={0.1}
								value={row.units}
								disabled={loading || saving}
								oninput={(e) => setRow(index, { units: (e.currentTarget as HTMLInputElement).value })}
								aria-label="Fill units for {row.partId || 'part'}"
							/>
						</div>
						<Button
							variant="ghost"
							size="sm"
							icon={Trash2}
							label="Remove {row.partId || 'this part'}"
							disabled={loading || saving}
							onclick={() => removeRow(index)}
						/>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	{#snippet footer()}
		<div class="flex w-full flex-wrap items-center justify-end gap-2">
			{#if configChanged()}
				<span class="mr-auto text-sm text-ink-muted">Unsaved changes</span>
			{/if}
			<Button variant="ghost" disabled={loading || saving} onclick={loadConfig}>Reload</Button>
			<Button variant="primary" loading={saving} disabled={loading} onclick={saveConfig}>
				Save the volumes
			</Button>
		</div>
	{/snippet}
</Panel>

{#if errorMsg}
	<Alert tone="danger">{errorMsg}</Alert>
{:else if statusMsg}
	<p class="text-sm text-ink-muted">{statusMsg}</p>
{/if}

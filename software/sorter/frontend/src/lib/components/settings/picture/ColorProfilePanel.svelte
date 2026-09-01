<script lang="ts" module>
	export type CameraColorProfile = {
		enabled: boolean;
		matrix: number[][];
		bias: number[];
	};

	export function hasCalibrationData(profile: CameraColorProfile | null): boolean {
		if (!profile) return false;
		const identity = [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1]
		];
		for (let r = 0; r < 3; r += 1) {
			for (let c = 0; c < 3; c += 1) {
				if (Math.abs((profile.matrix[r]?.[c] ?? 0) - identity[r][c]) > 0.0001) return true;
			}
			if (Math.abs(profile.bias[r] ?? 0) > 0.0001) return true;
		}
		return false;
	}

	export function normalizeCameraColorProfile(raw: unknown): CameraColorProfile {
		const identity = [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1]
		];
		if (!raw || typeof raw !== 'object') {
			return { enabled: false, matrix: identity, bias: [0, 0, 0] };
		}
		const record = raw as Record<string, unknown>;
		const rawMatrix = Array.isArray(record.matrix) ? record.matrix : [];
		const matrix: number[][] = [];
		for (let row = 0; row < 3; row += 1) {
			const rawRow = Array.isArray(rawMatrix[row]) ? (rawMatrix[row] as unknown[]) : [];
			const parsed: number[] = [];
			for (let col = 0; col < 3; col += 1) {
				const value = rawRow[col];
				parsed.push(typeof value === 'number' ? value : row === col ? 1 : 0);
			}
			matrix.push(parsed);
		}
		const rawBias = Array.isArray(record.bias) ? record.bias : [];
		const bias: number[] = [];
		for (let i = 0; i < 3; i += 1) {
			const value = rawBias[i];
			bias.push(typeof value === 'number' ? value : 0);
		}
		return {
			enabled: Boolean(record.enabled),
			matrix,
			bias
		};
	}
</script>

<script lang="ts">
	import { Palette, Trash2 } from 'lucide-svelte';

	let {
		profile,
		loading = false,
		removing = false,
		toggling = false,
		globallyEnabled = true,
		onReset,
		onToggleEnabled
	}: {
		profile: CameraColorProfile | null;
		loading?: boolean;
		removing?: boolean;
		toggling?: boolean;
		globallyEnabled?: boolean;
		onReset: () => void;
		onToggleEnabled: (enabled: boolean) => void;
	} = $props();

	const ROW_LABELS = ['R', 'G', 'B'] as const;

	// The per-camera toggle is meaningless while the system-wide kill switch is
	// off — nothing is applied regardless of what this profile says.
	const enabled = $derived(globallyEnabled && (profile?.enabled ?? false));
	const hasData = $derived(hasCalibrationData(profile));

	function formatCell(value: number): string {
		return value.toFixed(3);
	}
</script>

<div class={`grid gap-2 border-t border-border pt-3 ${globallyEnabled ? '' : 'opacity-60'}`}>
	<div class="flex items-center justify-between gap-3">
		<div class="flex items-center gap-2">
			<Palette size={14} class="text-text-muted" />
			<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
				Color Correction
			</span>
		</div>
		<button
			onclick={() => onToggleEnabled(!enabled)}
			disabled={loading || toggling || !globallyEnabled}
			title={globallyEnabled ? undefined : 'Color correction is disabled in the software build.'}
			class={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center border transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
				enabled ? 'border-success bg-success' : 'border-border bg-surface'
			}`}
			role="switch"
			aria-checked={enabled}
		>
			<span
				class={`inline-block h-3 w-3 border transition-transform ${
					enabled
						? 'translate-x-[18px] border-white bg-white'
						: 'translate-x-[2px] border-border bg-text-muted'
				}`}
			></span>
		</button>
	</div>

	{#if !globallyEnabled}
		<p class="text-sm leading-6 text-text-muted">
			Color correction is turned off in this software build, so no frames are corrected on any
			camera. {hasData
				? 'This camera still has a saved calibration — it is kept as-is and will apply again if color correction is turned back on.'
				: 'This camera has no saved calibration.'}
		</p>
	{:else if enabled}
		<p class="text-sm text-text-muted">
			Color correction applies a per-pixel matrix transform to every frame on every camera. This can
			be taxing on low-powered CPUs — only enable it if you need accurate color reproduction.
		</p>

		{#if loading}
			<div class="text-sm text-text-muted">Loading color profile...</div>
		{:else if !hasData}
			<div class="text-sm leading-6 text-text-muted">
				No color correction matrix saved. Run Target Plate or LLM calibration to generate one.
			</div>
		{:else}
			<div class="grid gap-2">
				<div
					class="grid grid-cols-[auto_repeat(3,minmax(0,1fr))] gap-px border border-border bg-border"
				>
					<div class="bg-surface px-2 py-1"></div>
					<div
						class="bg-surface px-2 py-1 text-center text-xs font-semibold tracking-wider text-text-muted uppercase"
					>
						R
					</div>
					<div
						class="bg-surface px-2 py-1 text-center text-xs font-semibold tracking-wider text-text-muted uppercase"
					>
						G
					</div>
					<div
						class="bg-surface px-2 py-1 text-center text-xs font-semibold tracking-wider text-text-muted uppercase"
					>
						B
					</div>
					{#each profile!.matrix as row, rowIndex}
						<div
							class="bg-surface px-2 py-1 text-xs font-semibold tracking-wider text-text-muted uppercase"
						>
							{ROW_LABELS[rowIndex]}
						</div>
						{#each row as cell}
							<div class="bg-bg px-2 py-1 text-center font-mono text-sm tabular-nums text-text">
								{formatCell(cell)}
							</div>
						{/each}
					{/each}
				</div>
				<div
					class="grid grid-cols-[auto_repeat(3,minmax(0,1fr))] gap-px border border-border bg-border"
				>
					<div
						class="bg-surface px-2 py-1 text-xs font-semibold tracking-wider text-text-muted uppercase"
					>
						Bias
					</div>
					{#each profile!.bias as value}
						<div class="bg-bg px-2 py-1 text-center font-mono text-sm tabular-nums text-text">
							{formatCell(value)}
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<button
			onclick={onReset}
			disabled={removing || loading || !hasData}
			class="inline-flex w-full cursor-pointer items-center justify-center gap-2 border border-danger bg-surface px-3 py-2 text-sm font-medium text-danger-dark transition-colors hover:bg-danger/[0.08] disabled:cursor-not-allowed disabled:opacity-50 dark:text-rose-300"
		>
			<Trash2 size={14} />
			<span>{removing ? 'Removing...' : 'Remove color correction'}</span>
		</button>
	{/if}
</div>

<script lang="ts" module>
	import type {
		CameraCalibrationAnalysis,
		CameraCalibrationMethod
	} from '$lib/settings/camera-device-settings';

	type CalibrationMethodOption = {
		value: CameraCalibrationMethod;
		label: string;
		description: string;
	};

	export const CALIBRATION_METHOD_OPTIONS: CalibrationMethodOption[] = [
		{
			value: 'target_plate',
			label: 'Target Plate Search',
			description:
				'Uses the built-in search and scoring pipeline to tune exposure and generate a color profile.'
		},
		{
			value: 'llm_guided',
			label: 'Smart LLM Calibration',
			description:
				'Sends the live frame plus current device settings to OpenRouter and iteratively applies suggested tuning changes.'
		}
	];

	const CALIBRATION_TILE_ORDER = [
		'white_top',
		'black_top',
		'blue',
		'red',
		'green',
		'yellow',
		'black_bottom',
		'white_bottom'
	] as const;

	const CALIBRATION_TILE_LABELS: Record<string, string> = {
		white_top: 'White Top',
		black_top: 'Black Top',
		white_bottom: 'White Bottom',
		black_bottom: 'Black Bottom',
		red: 'Red',
		yellow: 'Yellow',
		green: 'Green',
		blue: 'Blue'
	};

	const CALIBRATION_TILE_SWATCH: Record<string, string> = {
		white_top: '#f8fafc',
		black_top: '#111827',
		white_bottom: '#e2e8f0',
		black_bottom: '#1f2937',
		red: '#dc2626',
		yellow: '#eab308',
		green: '#16a34a',
		blue: '#0284c7'
	};

	export function selectedCalibrationMethodDescription(method: CameraCalibrationMethod): string {
		return (
			CALIBRATION_METHOD_OPTIONS.find((option) => option.value === method)?.description ?? ''
		);
	}

	export function calibrationStageLabel(stage: string): string {
		switch (stage) {
			case 'preparing':
				return 'Preparing';
			case 'llm_capture':
				return 'Capturing';
			case 'llm_review':
				return 'LLM Review';
			case 'llm_apply':
				return 'Applying Changes';
			case 'baseline':
				return 'Analyzing Baseline';
			case 'exposure_search':
				return 'Searching Exposure';
			case 'exposure_refine':
				return 'Refining Exposure';
			case 'white_balance_search':
				return 'Searching White Balance';
			case 'white_balance_refine':
				return 'Refining White Balance';
			case 'profile_generation':
				return 'Generating Color Profile';
			case 'tone_search':
				return 'Refining Tone Controls';
			case 'polish_search':
				return 'Polishing Calibration';
			case 'saving':
				return 'Saving';
			case 'verifying':
				return 'Verifying';
			case 'completed':
				return 'Completed';
			case 'failed':
				return 'Failed';
			default:
				return 'Starting';
		}
	}

	export type CalibrationTileEntry = {
		key: string;
		label: string;
		swatch: string;
		matchPercent: number;
		matchTone: 'good' | 'okay' | 'weak';
		luma: number;
		saturation: number;
		clip_fraction: number;
		shadow_fraction: number;
		reference_error: number;
		reference_match_percent: number;
	};

	export function calibrationTileEntries(
		analysis: CameraCalibrationAnalysis | null
	): CalibrationTileEntry[] {
		if (!analysis) return [];
		const entries: CalibrationTileEntry[] = [];
		for (const key of CALIBRATION_TILE_ORDER) {
			const sample = analysis.tile_samples[key];
			if (!sample) continue;
			const matchPercent = Math.max(0, Math.min(100, sample.reference_match_percent));
			entries.push({
				key,
				label: CALIBRATION_TILE_LABELS[key] ?? key,
				swatch: CALIBRATION_TILE_SWATCH[key] ?? '#94a3b8',
				matchPercent,
				matchTone: matchPercent >= 85 ? 'good' : matchPercent >= 65 ? 'okay' : 'weak',
				luma: sample.luma,
				saturation: sample.saturation,
				clip_fraction: sample.clip_fraction,
				shadow_fraction: sample.shadow_fraction,
				reference_error: sample.reference_error,
				reference_match_percent: sample.reference_match_percent
			});
		}
		return entries;
	}

	export function calibrationAverageMatch(analysis: CameraCalibrationAnalysis | null): number {
		const entries = calibrationTileEntries(analysis);
		if (entries.length === 0) return 0;
		return entries.reduce((sum, entry) => sum + entry.matchPercent, 0) / entries.length;
	}

	export function calibrationLowestMatch(analysis: CameraCalibrationAnalysis | null): number {
		const entries = calibrationTileEntries(analysis);
		if (entries.length === 0) return 0;
		return Math.min(...entries.map((entry) => entry.matchPercent));
	}

	type CalibrationFeedback = {
		tone: 'good' | 'okay' | 'weak';
		label: string;
		message: string;
	};

	export function calibrationFeedback(
		analysis: CameraCalibrationAnalysis | null
	): CalibrationFeedback | null {
		if (!analysis) return null;
		const averageMatch = calibrationAverageMatch(analysis);
		const lowestMatch = calibrationLowestMatch(analysis);
		if (averageMatch >= 80 && lowestMatch >= 60) {
			return {
				tone: 'good',
				label: 'Calibration looks solid',
				message: 'The checker is reading consistently across the target.'
			};
		}
		if (averageMatch >= 60 && lowestMatch >= 35) {
			return {
				tone: 'okay',
				label: 'Calibration is usable',
				message:
					'You can improve it further by reducing glare and filling more of the frame with the checker.'
			};
		}
		return {
			tone: 'weak',
			label: 'Calibration looks weak',
			message:
				'Try reducing glare, keeping the target flatter, and making the Color Check larger in the preview before recalibrating.'
		};
	}

	export function hasTileDetails(analysis: CameraCalibrationAnalysis | null): boolean {
		return !!analysis && Object.keys(analysis.tile_samples).length > 0;
	}

	export function calibrationSummaryVisible(
		analysis: CameraCalibrationAnalysis | null,
		calibrating: boolean,
		calibrationNeedsSave: boolean,
		calibrationStage: string
	): boolean {
		return !!analysis && !calibrating && (calibrationNeedsSave || calibrationStage === 'completed');
	}
</script>

<script lang="ts">
	import { ChevronDown } from 'lucide-svelte';

	let {
		calibrationMethod = $bindable(),
		calibrationApplyColorProfile = $bindable(true),
		calibrating,
		saving,
		hasCamera,
		calibrationReferenceImageSrc,
		calibrationReferenceLinkUrl,
		calibrationResult,
		calibrationStage,
		calibrationProgress,
		calibrationMessage,
		calibrationNeedsSave,
		onCalibrate
	}: {
		calibrationMethod: CameraCalibrationMethod;
		calibrationApplyColorProfile?: boolean;
		calibrating: boolean;
		saving: boolean;
		hasCamera: boolean;
		calibrationReferenceImageSrc: string;
		calibrationReferenceLinkUrl: string;
		calibrationResult: CameraCalibrationAnalysis | null;
		calibrationStage: string;
		calibrationProgress: number;
		calibrationMessage: string;
		calibrationNeedsSave: boolean;
		onCalibrate: () => void;
	} = $props();

	let calibrationTargetHelpOpen = $state(false);
</script>

<div class="grid gap-3">
	<div class="flex items-start gap-3">
		{#if calibrationReferenceImageSrc}
			<img
				src={calibrationReferenceImageSrc}
				alt="LEGO Color Check reference"
				class="h-16 w-16 shrink-0 border border-border bg-surface object-contain"
			/>
		{:else}
			<svg
				viewBox="0 0 40 60"
				width="36"
				height="54"
				class="shrink-0 rounded-sm border border-black/10 dark:border-white/10"
			>
				<rect x="0" y="0" width="10" height="10" fill="#f0f0f0" />
				<rect x="10" y="0" width="10" height="10" fill="#111111" />
				<rect x="20" y="0" width="10" height="10" fill="#e0eef8" />
				<rect x="30" y="0" width="10" height="10" fill="#0a0a2a" />
				<rect x="0" y="10" width="20" height="20" fill="#1a8cff" />
				<rect x="20" y="10" width="20" height="20" fill="#e02020" />
				<rect x="0" y="30" width="20" height="20" fill="#16a34a" />
				<rect x="20" y="30" width="20" height="20" fill="#eab308" />
				<rect x="0" y="50" width="10" height="10" fill="#0a0a2a" />
				<rect x="10" y="50" width="10" height="10" fill="#f0f0f0" />
				<rect x="20" y="50" width="10" height="10" fill="#222222" />
				<rect x="30" y="50" width="10" height="10" fill="#e0eef8" />
				<line x1="10" y1="0" x2="10" y2="60" stroke="#00000018" stroke-width="0.5" />
				<line x1="20" y1="0" x2="20" y2="60" stroke="#00000018" stroke-width="0.5" />
				<line x1="30" y1="0" x2="30" y2="60" stroke="#00000018" stroke-width="0.5" />
				<line x1="0" y1="10" x2="40" y2="10" stroke="#00000018" stroke-width="0.5" />
				<line x1="0" y1="20" x2="40" y2="20" stroke="#00000018" stroke-width="0.5" />
				<line x1="0" y1="30" x2="40" y2="30" stroke="#00000018" stroke-width="0.5" />
				<line x1="0" y1="40" x2="40" y2="40" stroke="#00000018" stroke-width="0.5" />
				<line x1="0" y1="50" x2="40" y2="50" stroke="#00000018" stroke-width="0.5" />
			</svg>
		{/if}
		<div class="min-w-0 text-xs leading-5 text-text-muted">
			<div class="font-medium text-text">How to calibrate</div>
			<div class="mt-1">
				{#if calibrationMethod === 'llm_guided'}
					Place the Color Check fully inside the live preview, keep it flat and well lit, and
					the LLM will iterate on the current frame plus device settings until it is satisfied.
				{:else}
					Place the Color Check fully inside the live preview, keep it flat and well lit, and
					use the preview to tune exposure, white balance, and orientation before you calibrate.
				{/if}
			</div>
		</div>
	</div>

	{#if calibrationReferenceLinkUrl}
		<div class="border-t border-border pt-3 text-xs leading-5 text-text-muted">
			<button
				onclick={() => (calibrationTargetHelpOpen = !calibrationTargetHelpOpen)}
				class="flex w-full cursor-pointer items-center justify-between gap-3 text-left transition-colors hover:text-text"
				aria-expanded={calibrationTargetHelpOpen}
			>
				<span class="font-medium text-text">Where do I get a calibration color checker?</span>
				<ChevronDown
					size={15}
					class={`shrink-0 text-text-muted transition-transform duration-200 ${calibrationTargetHelpOpen ? 'rotate-180' : ''}`}
				/>
			</button>
			{#if calibrationTargetHelpOpen}
				<div class="mt-2 grid gap-2 border-t border-border pt-2">
					<div>
						Use the BrickLink Studio model to buy the parts and rebuild the same LEGO Color
						Check target for your machine.
					</div>
					<a
						href={calibrationReferenceLinkUrl}
						target="_blank"
						rel="noreferrer"
						class="w-fit text-[11px] font-medium text-primary transition-colors hover:underline"
					>
						Open BrickLink model
					</a>
				</div>
			{/if}
		</div>
	{/if}

	{#if calibrationResult}
		<div
			class="border border-primary/40 bg-primary/[0.06] px-3 py-2 dark:border-[#4D8DFF]/40 dark:bg-[#4D8DFF]/[0.08]"
		>
			<div
				class="text-[11px] font-semibold tracking-wider text-primary-dark uppercase dark:text-[#7BAEFF]"
			>
				Calibration hint
			</div>
			<div class="mt-1 text-xs leading-relaxed text-text">
				The blue frame in the preview marks the detected Color Check area from the latest
				calibration pass.
			</div>
		</div>
	{/if}
</div>

<label class="flex flex-col gap-2">
	<div class="flex items-center justify-between gap-3 text-sm">
		<span class="font-medium text-text">Calibration Method</span>
	</div>
	<select
		class="border border-border bg-surface px-3 py-2 text-sm text-text"
		bind:value={calibrationMethod}
		disabled={calibrating || saving}
	>
		{#each CALIBRATION_METHOD_OPTIONS as option}
			<option value={option.value}>{option.label}</option>
		{/each}
	</select>
	<div class="text-sm leading-6 text-text-muted">
		{selectedCalibrationMethodDescription(calibrationMethod)}
	</div>
</label>

{#if calibrationMethod === 'llm_guided'}
	<label class="flex items-start gap-2 border border-border bg-surface px-3 py-2 text-sm text-text">
		<input
			type="checkbox"
			class="mt-0.5"
			bind:checked={calibrationApplyColorProfile}
			disabled={calibrating || saving}
		/>
		<span class="flex flex-col gap-0.5">
			<span class="font-medium">Apply final color correction</span>
			<span class="text-sm leading-6 text-text-muted">
				Generate and save a color profile from the target plate after the advisor finishes.
				Uncheck to tune device settings only and keep the live feed uncorrected.
			</span>
		</span>
	</label>
{/if}

<button
	onclick={onCalibrate}
	disabled={!hasCamera || calibrating || saving}
	class="inline-flex w-full cursor-pointer items-center justify-center gap-2 border border-primary bg-primary px-4 py-2 text-sm font-medium text-primary-contrast transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
>
	<span>
		{#if calibrating}
			Calibrating...
		{:else if calibrationMethod === 'llm_guided'}
			Calibrate with LLM
		{:else}
			Calibrate
		{/if}
	</span>
</button>

{#if calibrationResult}
	{@const summaryVisible = calibrationSummaryVisible(
		calibrationResult,
		calibrating,
		calibrationNeedsSave,
		calibrationStage
	)}
	<div class={`grid gap-1.5 ${summaryVisible ? 'grid-cols-2' : 'grid-cols-1'}`}>
		<div class="border border-border bg-bg px-2.5 py-2">
			<div class="text-[11px] tracking-wider text-text-muted uppercase">Match Avg</div>
			<div class="mt-0.5 font-mono text-sm text-text tabular-nums">
				{calibrationAverageMatch(calibrationResult).toFixed(0)}%
			</div>
		</div>
		{#if summaryVisible}
			<div class="border border-border bg-bg px-2.5 py-2">
				<div class="text-[11px] tracking-wider text-text-muted uppercase">Ref Error</div>
				<div class="mt-0.5 font-mono text-sm text-text tabular-nums">
					{calibrationResult.reference_color_error_mean.toFixed(1)}
				</div>
			</div>
			<div class="border border-border bg-bg px-2.5 py-2">
				<div class="text-[11px] tracking-wider text-text-muted uppercase">White / Black</div>
				<div class="mt-0.5 font-mono text-sm text-text tabular-nums">
					{calibrationResult.white_luma_mean.toFixed(1)} / {calibrationResult.black_luma_mean.toFixed(
						1
					)}
				</div>
			</div>
			<div class="border border-border bg-bg px-2.5 py-2">
				<div class="text-[11px] tracking-wider text-text-muted uppercase">WB Cast</div>
				<div class="mt-0.5 font-mono text-sm text-text tabular-nums">
					{calibrationResult.white_balance_cast.toFixed(3)}
				</div>
			</div>
		{/if}
	</div>

	{#if summaryVisible && calibrationFeedback(calibrationResult)}
		{@const feedback = calibrationFeedback(calibrationResult)}
		<div
			class={`border px-3 py-2 ${
				feedback?.tone === 'good'
					? 'border-success/40 bg-success/[0.06]'
					: feedback?.tone === 'okay'
						? 'border-warning/50 bg-warning/[0.07]'
						: 'border-danger/40 bg-danger/[0.06]'
			}`}
		>
			<div
				class={`text-[11px] font-semibold tracking-wider uppercase ${
					feedback?.tone === 'good'
						? 'text-success-dark dark:text-emerald-300'
						: feedback?.tone === 'okay'
							? 'text-warning-dark dark:text-amber-300'
							: 'text-danger-dark dark:text-rose-300'
				}`}
			>
				{feedback?.label}
			</div>
			<div class="mt-1 text-xs leading-relaxed text-text">{feedback?.message}</div>
		</div>
	{/if}

	{#if calibrationTileEntries(calibrationResult).length > 0}
		<div class="grid gap-2">
			<div class="text-[11px] font-semibold tracking-wider text-text-muted uppercase">
				Live Tile Levels
			</div>
			<div class="grid grid-cols-2 gap-1.5">
				{#each calibrationTileEntries(calibrationResult) as tile}
					<div
						class="flex items-center justify-between gap-2 border border-border bg-bg px-2.5 py-2"
					>
						<div class="flex min-w-0 items-center gap-2">
							<span
								class="inline-block h-3 w-3 shrink-0 rounded-[2px] border border-black/15"
								style={`background:${tile.swatch}`}
							></span>
							<span class="truncate text-xs text-text">{tile.label}</span>
						</div>
						<span
							class:text-success-dark={tile.matchTone === 'good'}
							class:text-warning-dark={tile.matchTone === 'okay'}
							class:text-danger-dark={tile.matchTone === 'weak'}
							class:dark:text-emerald-300={tile.matchTone === 'good'}
							class:dark:text-amber-300={tile.matchTone === 'okay'}
							class:dark:text-rose-300={tile.matchTone === 'weak'}
							class="font-mono text-xs font-semibold tabular-nums"
						>
							{tile.matchPercent.toFixed(0)}%
						</span>
					</div>
				{/each}
			</div>
		</div>
	{/if}
{/if}

{#if calibrating}
	<div class="flex flex-col gap-2">
		<div class="flex items-center justify-between gap-3 text-sm">
			<span class="font-medium text-text">
				{calibrationStageLabel(calibrationStage)}
			</span>
			<span class="font-mono text-text-muted">
				{Math.round(calibrationProgress * 100)}%
			</span>
		</div>
		<div class="h-2 overflow-hidden rounded-full bg-bg">
			<div
				class="h-full bg-sky-500 transition-[width] duration-300"
				style={`width: ${Math.max(4, Math.min(100, calibrationProgress * 100))}%`}
			></div>
		</div>
	</div>
{/if}

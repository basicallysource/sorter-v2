<script lang="ts">
	import { Maximize2 } from 'lucide-svelte';
	import type {
		CameraCalibrationAdvisorChange,
		CameraCalibrationAdvisorIteration,
		CameraCalibrationGalleryEntry,
		CameraCalibrationMethod
	} from '$lib/settings/camera-device-settings';

	let {
		method = 'llm_guided',
		active = false,
		taskId = null,
		entries = [],
		galleryEntries = [],
		backendBaseUrl,
		compact = false,
		onEnlarge = undefined
	}: {
		method?: CameraCalibrationMethod | string;
		active?: boolean;
		taskId?: string | null;
		entries?: CameraCalibrationAdvisorIteration[];
		galleryEntries?: CameraCalibrationGalleryEntry[];
		backendBaseUrl: string;
		compact?: boolean;
		onEnlarge?: (() => void) | undefined;
	} = $props();

	function visible(): boolean {
		return (
			method === 'llm_guided' &&
			(active || entries.length > 0 || galleryEntries.length > 0)
		);
	}

	function titleCaseWords(value: string): string {
		return value
			.split(/\s+/)
			.filter(Boolean)
			.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
			.join(' ');
	}

	function settingLabel(key: string): string {
		const normalized = key.trim().toLowerCase();
		const labels: Record<string, string> = {
			ae_lock: 'AE Lock',
			awb_lock: 'AWB Lock',
			auto_exposure: 'Auto Exposure',
			auto_focus: 'Auto Focus',
			auto_white_balance: 'Auto WB',
			backlight_compensation: 'Backlight Comp.',
			exposure_compensation: 'Exposure Comp.',
			power_line_frequency: 'Power Line Freq.',
			white_balance_temperature: 'WB Temperature'
		};
		return labels[normalized] ?? titleCaseWords(normalized.replace(/_/g, ' '));
	}

	function formatValue(value: unknown): string {
		if (typeof value === 'boolean') return value ? 'On' : 'Off';
		if (typeof value === 'number') {
			if (!Number.isFinite(value)) return 'n/a';
			if (Math.abs(value) >= 100 || Number.isInteger(value)) return String(Math.round(value));
			return value.toFixed(2).replace(/\.?0+$/, '');
		}
		if (typeof value === 'string') return value;
		if (value === null || value === undefined) return 'n/a';
		return String(value);
	}

	function currentValue(step: CameraCalibrationAdvisorIteration, key: string): unknown {
		const currentSettings = step.input?.current_settings;
		if (!currentSettings || typeof currentSettings !== 'object') return undefined;
		return (currentSettings as Record<string, unknown>)[key];
	}

	function changeFromValue(
		step: CameraCalibrationAdvisorIteration,
		change: CameraCalibrationAdvisorChange
	): string {
		const previous = currentValue(step, change.key);
		if (previous === undefined || previous === change.value) return '';
		return formatValue(previous);
	}

	function narration(step: CameraCalibrationAdvisorIteration): string {
		if (step.status === 'pending') {
			return 'Frame sent — waiting for the advisor to respond…';
		}
		const summary = step.summary?.trim();
		if (summary) return summary;
		if (step.stage === 'final_review') {
			if (step.status === 'approved') return 'Advisor signed off on the color-corrected image.';
			if (step.status === 'concerns')
				return 'Advisor flagged remaining concerns with the corrected image.';
			if (step.status === 'error') return 'Final-review call failed.';
			return 'Reviewing the color-corrected image.';
		}
		if (step.status === 'done') return 'The advisor is satisfied with the current image.';
		if (step.changes && step.changes.length > 0) {
			return `Adjusting ${step.changes.length} setting${step.changes.length === 1 ? '' : 's'}.`;
		}
		return 'Waiting for the advisor response.';
	}

	function imageUrl(url: string): string {
		if (/^https?:\/\//.test(url)) return url;
		if (url.startsWith('/')) return `${backendBaseUrl}${url}`;
		return `${backendBaseUrl}/${url}`;
	}

	function galleryCapture(iteration: number): CameraCalibrationGalleryEntry | null {
		return (
			galleryEntries.find(
				(entry) => entry.iteration === iteration && entry.stage === 'llm_capture'
			) ?? null
		);
	}

	function sentImageUrl(step: CameraCalibrationAdvisorIteration): string | null {
		if (typeof step.input_image_url === 'string' && step.input_image_url) {
			return step.input_image_url;
		}
		const entry = galleryCapture(step.iteration);
		return entry ? entry.image_url : null;
	}

	function statusBadgeClass(status: string): string {
		if (status === 'done' || status === 'approved') {
			return 'border-success/35 bg-success/[0.08] text-success-dark dark:border-emerald-500/35 dark:bg-emerald-500/[0.14] dark:text-emerald-200';
		}
		if (status === 'continue') {
			return 'border-[#4D8DFF]/35 bg-[#4D8DFF]/[0.08] text-[#113C8D] dark:border-sky-500/35 dark:bg-sky-500/[0.14] dark:text-sky-200';
		}
		if (status === 'pending') {
			return 'border-amber-500/35 bg-amber-500/[0.10] text-amber-900 dark:border-amber-400/35 dark:bg-amber-400/[0.14] dark:text-amber-200';
		}
		if (status === 'concerns' || status === 'error') {
			return 'border-rose-500/35 bg-rose-500/[0.10] text-rose-900 dark:border-rose-400/35 dark:bg-rose-400/[0.14] dark:text-rose-200';
		}
		return 'border-border bg-surface text-text-muted';
	}

	function statusLabel(status: string): string {
		if (status === 'done') return 'Satisfied';
		if (status === 'continue') return 'Adjust';
		if (status === 'pending') return 'Waiting…';
		if (status === 'approved') return 'Approved';
		if (status === 'concerns') return 'Concerns';
		if (status === 'error') return 'Error';
		return status || 'Step';
	}

	function isFinalReview(step: CameraCalibrationAdvisorIteration): boolean {
		return step.stage === 'final_review';
	}

	function reviewConcerns(step: CameraCalibrationAdvisorIteration): string[] {
		const raw = step.response?.concerns;
		if (!Array.isArray(raw)) return [];
		const out: string[] = [];
		for (const item of raw) {
			if (typeof item === 'string' && item.trim()) out.push(item.trim());
		}
		return out;
	}
</script>

{#if visible()}
	{@const headerTitleClass = compact ? 'text-sm' : 'text-base'}
	{@const taskIdClass = 'text-xs'}
	{@const enlargeBtnClass = compact ? 'text-xs' : 'text-sm'}
	{@const emptyTextClass = 'text-sm'}
	{@const cardLabelClass = 'text-xs'}
	{@const imageHeightClass = compact ? 'max-h-56' : 'max-h-[70vh]'}
	{@const imagePlaceholderClass = compact ? 'min-h-24 text-sm' : 'min-h-48 text-sm'}
	{@const waitingTextClass = 'text-sm'}
	{@const statusBadgeSize = 'text-xs'}
	{@const narrationClass = 'text-sm leading-6'}
	{@const tableTextClass = 'text-sm'}
	{@const tableHeaderClass = 'text-xs'}
	{@const tableCellPad = compact ? 'px-2 py-1' : 'px-2.5 py-1.5'}
	{@const cardPad = compact ? 'p-2' : 'p-3'}
	{@const concernTextClass = 'text-sm leading-6'}

	<div class="border border-border bg-surface">
		<div class="flex items-start justify-between gap-2 border-b border-border px-3 py-2">
			<div class="min-w-0">
				<div class={`${headerTitleClass} font-semibold text-text`}>LLM Calibration Log</div>
				{#if taskId && !compact}
					<div class={`mt-0.5 font-mono ${taskIdClass} text-text-muted`}>Task {taskId}</div>
				{/if}
			</div>
			{#if onEnlarge}
				<button
					type="button"
					onclick={onEnlarge}
					class={`inline-flex shrink-0 cursor-pointer items-center gap-1 border border-border bg-bg px-2 py-1 ${enlargeBtnClass} text-text transition-colors hover:bg-surface`}
					title="Open enlarged view"
				>
					<Maximize2 size={compact ? 12 : 14} />
					<span>Enlarge</span>
				</button>
			{/if}
		</div>

		<div class={`flex flex-col gap-2 px-3 ${compact ? 'py-2' : 'py-3'}`}>
			{#if entries.length === 0}
				<div class={`flex items-center gap-2 border border-dashed border-border bg-white px-2.5 py-2 ${emptyTextClass} text-text-muted dark:bg-bg`}>
					<span class="inline-block h-2 w-2 animate-pulse bg-amber-500"></span>
					Capturing first frame…
				</div>
			{:else}
				{#each entries as step (step.iteration)}
					{@const sent = sentImageUrl(step)}
					{@const finalReview = isFinalReview(step)}
					{@const concerns = finalReview ? reviewConcerns(step) : []}
					{@const pending = step.status === 'pending'}

					<div class={`grid gap-1.5 border border-border bg-white dark:bg-bg ${cardPad}`}>
						<div class={`${cardLabelClass} font-semibold tracking-wider text-text-muted uppercase`}>
							{finalReview ? 'Sent corrected frame' : `Sent frame · iter ${step.iteration}`}
						</div>
						{#if sent}
							<img
								src={imageUrl(sent)}
								alt={`Advisor frame ${step.iteration}`}
								class={`w-full border border-border bg-black object-contain ${imageHeightClass}`}
								loading="lazy"
							/>
						{:else}
							<div
								class={`flex items-center justify-center border border-dashed border-border bg-surface px-3 text-text-muted ${imagePlaceholderClass}`}
							>
								Capturing frame…
							</div>
						{/if}
						{#if pending}
							<div class={`flex items-center gap-2 ${waitingTextClass} text-text-muted`}>
								<span class="inline-block h-2 w-2 shrink-0 animate-pulse bg-amber-500"></span>
								<span>Waiting for advisor…</span>
							</div>
						{/if}
					</div>

					{#if !pending}
						<div class={`grid gap-1.5 border border-border bg-surface ${cardPad}`}>
							<div class="flex items-center justify-between gap-2">
								<div class={`${cardLabelClass} font-semibold tracking-wider text-text-muted uppercase`}>
									Advisor reply
								</div>
								<div
									class={`inline-flex items-center border px-1.5 py-0.5 ${statusBadgeSize} font-medium tracking-wider uppercase ${statusBadgeClass(step.status)}`}
								>
									{statusLabel(step.status)}
								</div>
							</div>

							<div class={`${narrationClass} text-text`}>{narration(step)}</div>

							{#if step.changes && step.changes.length > 0 && !finalReview}
								<div class="overflow-x-auto border border-border bg-white dark:bg-bg">
									<table class={`w-full border-collapse ${tableTextClass}`}>
										<thead>
											<tr
												class={`border-b border-border text-left ${tableHeaderClass} font-semibold tracking-wider text-text-muted uppercase`}
											>
												<th class={tableCellPad}>Setting</th>
												<th class={`${tableCellPad} text-right`}>From</th>
												<th class={`${tableCellPad} text-right`}>To</th>
											</tr>
										</thead>
										<tbody>
											{#each step.changes as change}
												{@const fromValue = changeFromValue(step, change)}
												<tr class="border-t border-border align-top">
													<td class={`${tableCellPad} font-medium text-text whitespace-nowrap`}>
														{settingLabel(change.key)}
													</td>
													<td class={`${tableCellPad} text-right font-mono text-text-muted whitespace-nowrap`}>
														{fromValue || '—'}
													</td>
													<td class={`${tableCellPad} text-right font-mono text-text whitespace-nowrap`}>
														{formatValue(change.value)}
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{/if}

							{#if finalReview && concerns.length > 0}
								<ul class={`border border-border bg-white px-2.5 py-1.5 ${concernTextClass} text-text dark:bg-bg`}>
									{#each concerns as concern}
										<li class="ml-3 list-disc pl-1">{concern}</li>
									{/each}
								</ul>
							{/if}
						</div>
					{/if}
				{/each}
			{/if}
		</div>
	</div>
{/if}

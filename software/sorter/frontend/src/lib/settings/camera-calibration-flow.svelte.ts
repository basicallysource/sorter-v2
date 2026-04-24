import type {
	CameraCalibrationAnalysis,
	CameraCalibrationAdvisorIteration,
	CameraCalibrationGalleryEntry,
	CameraCalibrationMethod,
	CameraCalibrationTaskStatusResponse
} from '$lib/settings/camera-device-settings';
import {
	loadCameraCalibrationGallery,
	loadCameraCalibrationTask,
	startCameraCalibration
} from '$lib/settings/camera-settings-service';
import {
	normalizeCameraCalibrationAdvisorTrace,
	normalizeCameraCalibrationGalleryEntries
} from '$lib/settings/camera-device-settings';
import type { CameraRole } from '$lib/settings/stations';

const POLL_DELAY_MS = 450;

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export function normalizeCalibrationAnalysis(value: unknown): CameraCalibrationAnalysis | null {
	if (!value || typeof value !== 'object') return null;
	const record = value as Record<string, unknown>;
	const pattern = Array.isArray(record.pattern_size)
		? record.pattern_size.filter((item): item is number => typeof item === 'number')
		: [];
	const bbox = Array.isArray(record.board_bbox)
		? record.board_bbox.filter((item): item is number => typeof item === 'number')
		: [];
	const normalizedBbox = Array.isArray(record.normalized_board_bbox)
		? record.normalized_board_bbox.filter((item): item is number => typeof item === 'number')
		: [];
	if (pattern.length !== 2 || bbox.length !== 4 || normalizedBbox.length !== 4) return null;
	const numbers = [
		'total_cells',
		'bright_cell_count',
		'dark_cell_count',
		'color_cell_count',
		'score',
		'white_luma_mean',
		'black_luma_mean',
		'neutral_contrast',
		'clipped_white_fraction',
		'shadow_black_fraction',
		'white_balance_cast',
		'color_separation',
		'colorfulness',
		'reference_color_error_mean'
	] as const;
	for (const key of numbers) {
		if (typeof record[key] !== 'number') return null;
	}
	const tileSamples: CameraCalibrationAnalysis['tile_samples'] = {};
	if (record.tile_samples && typeof record.tile_samples === 'object') {
		for (const [key, rawValue] of Object.entries(record.tile_samples as Record<string, unknown>)) {
			if (!rawValue || typeof rawValue !== 'object') continue;
			const sample = rawValue as Record<string, unknown>;
			if (
				typeof sample.luma !== 'number' ||
				typeof sample.saturation !== 'number' ||
				typeof sample.clip_fraction !== 'number' ||
				typeof sample.shadow_fraction !== 'number' ||
				typeof sample.reference_error !== 'number' ||
				typeof sample.reference_match_percent !== 'number'
			) {
				continue;
			}
			tileSamples[key] = {
				luma: sample.luma,
				saturation: sample.saturation,
				clip_fraction: sample.clip_fraction,
				shadow_fraction: sample.shadow_fraction,
				reference_error: sample.reference_error,
				reference_match_percent: sample.reference_match_percent
			};
		}
	}
	return {
		pattern_size: [pattern[0], pattern[1]],
		board_bbox: [bbox[0], bbox[1], bbox[2], bbox[3]],
		normalized_board_bbox: [
			normalizedBbox[0],
			normalizedBbox[1],
			normalizedBbox[2],
			normalizedBbox[3]
		],
		total_cells: record.total_cells as number,
		bright_cell_count: record.bright_cell_count as number,
		dark_cell_count: record.dark_cell_count as number,
		color_cell_count: record.color_cell_count as number,
		score: record.score as number,
		white_luma_mean: record.white_luma_mean as number,
		black_luma_mean: record.black_luma_mean as number,
		neutral_contrast: record.neutral_contrast as number,
		clipped_white_fraction: record.clipped_white_fraction as number,
		shadow_black_fraction: record.shadow_black_fraction as number,
		white_balance_cast: record.white_balance_cast as number,
		color_separation: record.color_separation as number,
		colorfulness: record.colorfulness as number,
		reference_color_error_mean: record.reference_color_error_mean as number,
		tile_samples: tileSamples
	};
}

export function calibrationTraceLatestSummary(trace: CameraCalibrationAdvisorIteration[]): string {
	for (let index = trace.length - 1; index >= 0; index -= 1) {
		const summary = trace[index]?.summary?.trim();
		if (summary) return summary;
	}
	return '';
}

export type CameraCalibrationFlowUpdate = {
	taskId?: string;
	openrouterModel?: string;
	stage?: string;
	progress?: number;
	message?: string;
	advisorTrace?: CameraCalibrationAdvisorIteration[];
	galleryEntries?: CameraCalibrationGalleryEntry[];
	analysisPreview?: CameraCalibrationAnalysis | null;
	analysisResult?: CameraCalibrationAnalysis | null;
};

export async function runCameraCalibrationFlow(options: {
	role: CameraRole;
	method: CameraCalibrationMethod;
	openrouterModel: string;
	applyColorProfile: boolean;
	onUpdate: (update: CameraCalibrationFlowUpdate) => void | Promise<void>;
	baseUrl?: string;
}): Promise<CameraCalibrationTaskStatusResponse> {
	const start = await startCameraCalibration(
		options.role,
		options.method === 'llm_guided'
			? {
					method: options.method,
					openrouter_model: options.openrouterModel,
					apply_color_profile: options.applyColorProfile
				}
			: { method: options.method },
		{ baseUrl: options.baseUrl }
	);

	await options.onUpdate({
		taskId: start.task_id,
		openrouterModel:
			typeof start.openrouter_model === 'string' && start.openrouter_model
				? start.openrouter_model
				: undefined
	});

	while (true) {
		await delay(POLL_DELAY_MS);
		const task = await loadCameraCalibrationTask(options.role, start.task_id, {
			baseUrl: options.baseUrl
		});
		const advisorTrace = normalizeCameraCalibrationAdvisorTrace(
			task.advisor_trace ?? task.result?.advisor_trace
		);
		let galleryEntries: CameraCalibrationGalleryEntry[] | undefined;
		if (options.method === 'llm_guided') {
			try {
				const gallery = await loadCameraCalibrationGallery(options.role, start.task_id, {
					baseUrl: options.baseUrl
				});
				galleryEntries = normalizeCameraCalibrationGalleryEntries(gallery.entries);
			} catch {
				galleryEntries = [];
			}
		}

		await options.onUpdate({
			stage: task.stage ?? '',
			progress: typeof task.progress === 'number' ? task.progress : undefined,
			message:
				task.message ||
				(options.method === 'llm_guided' && advisorTrace.length > 0
					? calibrationTraceLatestSummary(advisorTrace)
					: undefined),
			advisorTrace,
			galleryEntries,
			analysisPreview: normalizeCalibrationAnalysis(task.analysis_preview),
			analysisResult: normalizeCalibrationAnalysis(task.result?.analysis)
		});

		if (task.status === 'completed') return task;
		if (task.status === 'failed') {
			throw new Error(
				task.error ??
					task.message ??
					(options.method === 'llm_guided'
						? 'Failed to calibrate camera with the LLM advisor'
						: 'Failed to calibrate camera from target plate')
			);
		}
	}
}

<script lang="ts">
	import { mjpegStream } from '$lib/actions/mjpegStream';
	import PictureSettingsSidebar from '$lib/components/settings/PictureSettingsSidebar.svelte';
	import { pictureSettingsEqual, type PictureSettings } from '$lib/settings/picture-settings';
	import type { CameraRole } from '$lib/settings/stations';
	import { createEventDispatcher } from 'svelte';

	type CalibrationHighlight = [number, number, number, number];
	type PreviewImageSize = { width: number; height: number };
	type TransformMatrix = [number, number, number, number];
	type PicturePreviewState = {
		saved: PictureSettings;
		draft: PictureSettings;
	};

	const COLOR_CHECKER_REFERENCE_IMAGE = '/setup/color-checker-reference.png';
	const COLOR_CHECKER_BRICKLINK_URL =
		'https://www.bricklink.com/v3/studio/design.page?idModel=810209';

	let {
		role,
		label,
		source = null,
		hasCamera = true,
		backendBaseUrl
	}: {
		role: CameraRole;
		label: string;
		source?: number | string | null;
		hasCamera?: boolean;
		backendBaseUrl: string;
	} = $props();

	const dispatch = createEventDispatcher<{ saved: void }>();

	let picturePreview = $state<PicturePreviewState | null>(null);
	let calibrationHighlight = $state<CalibrationHighlight | null>(null);
	let previewViewportEl: HTMLDivElement | null = null;
	let previewViewportSize = $state<PreviewImageSize>({ width: 0, height: 0 });
	let previewImageSize = $state<PreviewImageSize>({ width: 0, height: 0 });
	let feedRevision = $state(0);
	let previewKey = $state('');

	$effect(() => {
		const nextKey = `${role}::${typeof source === 'string' ? source : source === null ? 'none' : source}`;
		if (nextKey === previewKey) return;
		previewKey = nextKey;
		picturePreview = null;
		calibrationHighlight = null;
		previewImageSize = { width: 0, height: 0 };
		feedRevision += 1;
	});

	function updatePreviewViewportSize() {
		if (!previewViewportEl) return;
		const rect = previewViewportEl.getBoundingClientRect();
		const width = Math.max(0, Math.round(rect.width));
		const height = Math.max(0, Math.round(rect.height));
		if (width === previewViewportSize.width && height === previewViewportSize.height) return;
		previewViewportSize = { width, height };
	}

	$effect(() => {
		if (!previewViewportEl || typeof ResizeObserver === 'undefined') {
			previewViewportSize = { width: 0, height: 0 };
			return;
		}

		const observer = new ResizeObserver(() => updatePreviewViewportSize());
		updatePreviewViewportSize();
		observer.observe(previewViewportEl);
		return () => observer.disconnect();
	});

	function rememberPreviewImageSize(image: HTMLImageElement | null) {
		if (!image) return;
		const width = image.naturalWidth;
		const height = image.naturalHeight;
		if (width <= 0 || height <= 0) return;
		if (width === previewImageSize.width && height === previewImageSize.height) return;
		previewImageSize = { width, height };
	}

	function containedImageRect(
		container: PreviewImageSize,
		sourceSize: PreviewImageSize
	): { left: number; top: number; width: number; height: number } {
		if (
			container.width <= 0 ||
			container.height <= 0 ||
			sourceSize.width <= 0 ||
			sourceSize.height <= 0
		) {
			return {
				left: 0,
				top: 0,
				width: container.width,
				height: container.height
			};
		}

		const scale = Math.min(container.width / sourceSize.width, container.height / sourceSize.height);
		const width = sourceSize.width * scale;
		const height = sourceSize.height * scale;
		return {
			left: (container.width - width) / 2,
			top: (container.height - height) / 2,
			width,
			height
		};
	}

	function multiplyTransformMatrices(
		left: TransformMatrix,
		right: TransformMatrix
	): TransformMatrix {
		return [
			left[0] * right[0] + left[1] * right[2],
			left[0] * right[1] + left[1] * right[3],
			left[2] * right[0] + left[3] * right[2],
			left[2] * right[1] + left[3] * right[3]
		];
	}

	function inverseTransformMatrix(matrix: TransformMatrix): TransformMatrix {
		return [matrix[0], matrix[2], matrix[1], matrix[3]];
	}

	function pictureTransformMatrix(settings: PictureSettings): TransformMatrix {
		let matrix: TransformMatrix = [1, 0, 0, 1];

		const rotationMatrix: Record<number, TransformMatrix> = {
			0: [1, 0, 0, 1],
			90: [0, -1, 1, 0],
			180: [-1, 0, 0, -1],
			270: [0, 1, -1, 0]
		};

		matrix = multiplyTransformMatrices(rotationMatrix[settings.rotation] ?? rotationMatrix[0], matrix);
		if (settings.flip_horizontal) {
			matrix = multiplyTransformMatrices([-1, 0, 0, 1], matrix);
		}
		if (settings.flip_vertical) {
			matrix = multiplyTransformMatrices([1, 0, 0, -1], matrix);
		}
		return matrix;
	}

	function previewTransformStyle(): string {
		if (!picturePreview || pictureSettingsEqual(picturePreview.saved, picturePreview.draft)) return '';

		const relativeMatrix = multiplyTransformMatrices(
			pictureTransformMatrix(picturePreview.draft),
			inverseTransformMatrix(pictureTransformMatrix(picturePreview.saved))
		);

		const isIdentity =
			relativeMatrix[0] === 1 &&
			relativeMatrix[1] === 0 &&
			relativeMatrix[2] === 0 &&
			relativeMatrix[3] === 1;

		if (isIdentity) return '';
		return `transform: matrix(${relativeMatrix[0]}, ${relativeMatrix[2]}, ${relativeMatrix[1]}, ${relativeMatrix[3]}, 0, 0); transform-origin: center center;`;
	}

	function previewOverlayStyle(): string {
		const transformStyle = previewTransformStyle();
		if (previewImageSize.width <= 0 || previewImageSize.height <= 0) {
			return `inset:0;${transformStyle}`;
		}
		const fitted = containedImageRect(previewViewportSize, previewImageSize);
		return `left:${fitted.left}px;top:${fitted.top}px;width:${fitted.width}px;height:${fitted.height}px;${transformStyle}`;
	}

	function streamUrl(): string {
		return `${backendBaseUrl}/api/cameras/feed/${role}?annotated=false&v=${feedRevision}`;
	}

	function handleSidebarSaved() {
		picturePreview = null;
		feedRevision += 1;
		dispatch('saved');
	}

</script>

<div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem] xl:items-start">
	<div class="flex min-w-0 flex-col gap-3">
		<div class="relative overflow-hidden bg-black">
			<div
				class="relative min-h-[24rem] sm:min-h-[30rem] lg:min-h-[36rem] xl:min-h-[42rem]"
				bind:this={previewViewportEl}
			>
				{#if hasCamera}
					{#key `${role}::${typeof source === 'string' ? source : source === null ? 'none' : source}::${feedRevision}`}
						<img
							use:mjpegStream={{
								url: streamUrl(),
								firstFrameTimeoutMs: 6000,
								stallTimeoutMs: 4000
							}}
							alt={label}
							class="absolute inset-0 h-full w-full object-contain"
							style={previewTransformStyle()}
							onload={(event) =>
								rememberPreviewImageSize(event.currentTarget as HTMLImageElement)}
						/>
						<div class="pointer-events-none absolute" style={previewOverlayStyle()}>
							{#if calibrationHighlight}
								<div
									class="absolute border-2 border-sky-400 shadow-[0_0_0_1px_rgba(255,255,255,0.35),0_0_24px_rgba(56,189,248,0.35)]"
									style={`left:${calibrationHighlight[0] * 100}%;top:${calibrationHighlight[1] * 100}%;width:${(calibrationHighlight[2] - calibrationHighlight[0]) * 100}%;height:${(calibrationHighlight[3] - calibrationHighlight[1]) * 100}%;`}
								>
									<div class="absolute -top-7 left-0 rounded bg-sky-400 px-2 py-1 text-xs font-medium text-slate-950 shadow-md">
										Color Check
									</div>
								</div>
							{/if}
						</div>
					{/key}
				{:else}
					<div class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-white/80">
						<div class="max-w-sm rounded-md bg-black/55 px-4 py-3">
							Assign a camera first so you can preview picture settings and place the Color Check target.
						</div>
					</div>
				{/if}
			</div>
		</div>

	</div>

	<PictureSettingsSidebar
		{role}
		{label}
		{source}
		{hasCamera}
		showHeader={false}
		calibrationReferenceImageSrc={COLOR_CHECKER_REFERENCE_IMAGE}
		calibrationReferenceLinkUrl={COLOR_CHECKER_BRICKLINK_URL}
		primaryActionLabel="Confirm"
		allowPrimaryActionWithoutChanges={true}
		onSaved={handleSidebarSaved}
		onPreviewChange={(roleName, savedSettings, draftSettings) => {
			void roleName;
			picturePreview = {
				saved: savedSettings,
				draft: draftSettings
			};
		}}
		onCalibrationHighlightChange={(bbox) => {
			calibrationHighlight = bbox;
		}}
	/>
</div>

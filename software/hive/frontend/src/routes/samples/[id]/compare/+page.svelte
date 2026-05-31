<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { auth } from '$lib/auth.svelte';
	import {
		api,
		type SampleDetail,
		type TeacherModelInfo,
		type TeacherPreviewResponse
	} from '$lib/api';
	import ModelCompareTile from '$lib/components/teacher/ModelCompareTile.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	const sampleId = $derived(page.params.id ?? '');

	let sample = $state<SampleDetail | null>(null);
	let models = $state<TeacherModelInfo[]>([]);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	type RunStatus = 'idle' | 'running' | 'done' | 'error';
	type RunRow = {
		model: TeacherModelInfo;
		color: string;
		status: RunStatus;
		result: TeacherPreviewResponse | null;
		error: string | null;
	};

	const PALETTE = [
		'#D01012', '#0055BF', '#00852B', '#FFD500',
		'#A455D2', '#FF8C1A', '#1AC4D0', '#9B1D20',
		'#3D7A00', '#7A5400', '#A6093D', '#2E2E2E'
	];

	let rows = $state<RunRow[]>([]);

	// Prompt editing — the textarea is prefilled from the *chat-style* default prompt
	// (Gemini-shaped, applies to all openrouter_chat adapters). Perceptron has its own
	// short instruction; if the admin types here we still send the same override to it,
	// which is intentional — lets you A/B test the same instruction against both adapter
	// kinds. Leave blank to fall back to each adapter's own default.
	let promptText = $state('');
	let defaultPrompt = $state('');
	let promptDirty = $state(false);
	let promptLoadError = $state<string | null>(null);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void load();
	});

	async function load() {
		loading = true;
		loadError = null;
		try {
			const [s, m] = await Promise.all([api.getSample(sampleId), api.listTeacherModels()]);
			sample = s;
			models = m;
			rows = m.map((mod, i) => ({
				model: mod,
				color: PALETTE[i % PALETTE.length],
				status: 'idle',
				result: null,
				error: null
			}));
			// Pull the default chat prompt for prefill. Use the first openrouter_chat model.
			const defaultModel = m.find((mm) => mm.adapter_kind === 'openrouter_chat') ?? m[0];
			if (defaultModel) {
				try {
					const promptResp = await api.getSampleTeacherPrompt(s.id, defaultModel.model_id);
					defaultPrompt = promptResp.prompt;
					promptText = promptResp.prompt;
				} catch (e: unknown) {
					promptLoadError =
						e && typeof e === 'object' && 'error' in e
							? String((e as { error: unknown }).error)
							: 'Failed to load default prompt';
				}
			}
		} catch (e: unknown) {
			loadError =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Failed to load compare page';
		} finally {
			loading = false;
		}
	}

	function resetPrompt() {
		promptText = defaultPrompt;
		promptDirty = false;
	}

	function onPromptInput() {
		promptDirty = promptText !== defaultPrompt;
	}

	async function runOne(index: number) {
		const row = rows[index];
		if (!row || !sample) return;
		row.status = 'running';
		row.error = null;
		row.result = null;
		rows = [...rows];
		try {
			// Only send the override if the admin actually changed it from the default —
			// otherwise let each adapter use its own native default (Perceptron's is much
			// shorter than the Gemini-style chat prompt).
			const override = promptDirty ? promptText : null;
			const result = await api.previewSampleTeacher(sample.id, row.model.model_id, override);
			row.result = result;
			row.status = 'done';
		} catch (e: unknown) {
			row.error =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Preview failed';
			row.status = 'error';
		} finally {
			rows = [...rows];
		}
	}

	async function runAll() {
		await Promise.all(rows.map((_, i) => runOne(i)));
	}
</script>

<svelte:head>
	<title>Compare models · Sample · Hive</title>
</svelte:head>

<div class="mb-5 flex items-end justify-between gap-3">
	<div>
		<div class="mb-1 text-xs text-text-muted">
			<a href="/samples" class="hover:underline">Samples</a>
			<span class="mx-1">/</span>
			{#if sample}
				<a href={`/samples/${sample.id}`} class="hover:underline">{sample.local_sample_id.slice(0, 12)}</a>
				<span class="mx-1">/</span>
			{/if}
			<span>Compare models</span>
		</div>
		<h1 class="text-2xl font-bold text-text">Compare teacher models</h1>
		<p class="mt-1 text-sm text-text-muted">
			One image tile per model. Non-destructive — the sample's stored detection is not touched.
		</p>
	</div>
	<div class="flex items-center gap-2">
		<Button variant="primary" size="sm" onclick={runAll}>Run all models</Button>
	</div>
</div>

{#if loading}
	<Spinner />
{:else if loadError}
	<div class="border border-border bg-surface px-6 py-10 text-center text-sm text-text-muted">
		{loadError}
	</div>
{:else if !sample}
	<div class="border border-border bg-surface px-6 py-10 text-center text-sm text-text-muted">
		Sample not found.
	</div>
{:else}
	<details class="mb-5 border border-border bg-surface" open>
		<summary class="flex cursor-pointer items-center justify-between gap-2 border-b border-border px-4 py-2.5">
			<div class="flex items-center gap-2">
				<span class="text-sm font-semibold text-text">Prompt</span>
				{#if promptDirty}
					<span class="bg-warning-bg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warning-strong">
						modified
					</span>
				{:else}
					<span class="text-[11px] text-text-muted">(default)</span>
				{/if}
			</div>
			<div class="flex items-center gap-2 text-[11px] text-text-muted">
				<span>{promptText.length} chars</span>
				{#if promptDirty}
					<button
						type="button"
						onclick={(e) => { e.preventDefault(); e.stopPropagation(); resetPrompt(); }}
						class="text-primary hover:underline"
					>
						Reset to default
					</button>
				{/if}
			</div>
		</summary>
		<div class="px-4 py-3">
			{#if promptLoadError}
				<div class="mb-2 border border-warning-strong bg-warning-bg px-3 py-2 text-[11px] text-warning-strong">
					{promptLoadError}
				</div>
			{/if}
			<textarea
				bind:value={promptText}
				oninput={onPromptInput}
				rows="12"
				class="w-full resize-y border border-border bg-surface px-3 py-2 font-mono text-[12px] leading-relaxed text-text focus:border-primary focus:outline-none"
			></textarea>
			<p class="mt-2 text-[11px] text-text-muted">
				Modified prompt is sent verbatim to every <em>chat-style</em> adapter on the next Run.
				<strong>Perceptron Mk1 ignores this textarea</strong> — its native grounding mode
				needs a short declarative instruction and breaks into conversational prose when fed
				a long chat prompt. Perceptron always runs on its own internal instruction.
			</p>
		</div>
	</details>

	<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
		{#each rows as row, index (row.model.model_id)}
			<ModelCompareTile
				model={row.model}
				color={row.color}
				imageUrl={api.sampleImageUrl(sample.id)}
				status={row.status}
				result={row.result}
				error={row.error}
				onRun={() => runOne(index)}
			/>
		{/each}
	</div>
{/if}

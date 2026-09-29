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
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ImageOff from '@lucide/svelte/icons/image-off';
	import Play from '@lucide/svelte/icons/play';

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
	<title>Compare models - Hive</title>
</svelte:head>

<div>
	<Button href={`/samples/${sampleId}`} size="sm" variant="ghost" icon={ArrowLeft}>Sample</Button>
</div>

<PageHeader
	title="Compare teacher models"
	description="One picture for each model. Nothing is saved: the sample's own detection stays as it is."
>
	{#snippet actions()}
		<Button variant="primary" icon={Play} onclick={runAll}>Run every model</Button>
	{/snippet}
</PageHeader>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if loadError}
	<Alert tone="danger">{loadError}</Alert>
{:else if !sample}
	<Panel><EmptyState icon={ImageOff} title="Sample not found" /></Panel>
{:else}
	<Panel flush>
		<Disclosure title="Prompt" help={promptDirty ? 'Changed' : 'The default'} open>
			<div class="flex flex-col gap-3 px-(--pad-panel) pb-2">
				{#if promptLoadError}<Alert tone="warning">{promptLoadError}</Alert>{/if}
				<Textarea bind:value={promptText} oninput={onPromptInput} rows={12} class="font-mono" />
				<div class="flex flex-wrap items-start justify-between gap-3">
					<p class="max-w-3xl text-sm text-ink-muted">
						A changed prompt goes as it is to every chat-style adapter on the next run. Perceptron Mk1 ignores it: its
						grounding mode needs a short instruction of its own, and a long chat prompt turns its answer into prose.
					</p>
					<div class="flex items-center gap-2">
						<span class="num text-sm text-ink-muted">{promptText.length} characters</span>
						{#if promptDirty}<Button size="sm" variant="ghost" onclick={resetPrompt}>Reset to the default</Button>{/if}
					</div>
				</div>
			</div>
		</Disclosure>
	</Panel>

	<div class="grid gap-(--gap-panels) md:grid-cols-2 xl:grid-cols-3">
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

<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type TeacherPromptEntry } from '$lib/api';

	const ZONES = [
		{ key: 'classification_channel', label: 'C-Channel 4 (Classification)' },
		{ key: 'c_channel', label: 'C-Channels 1–3' },
		{ key: 'classification_chamber', label: 'Classification Chamber' },
		{ key: 'carousel', label: 'Carousel' }
	];
	const KINDS = [
		{ key: 'chat', label: 'Chat models (Gemini/Grok/etc.)' },
		{ key: 'perceptron', label: 'Perceptron' }
	];

	let entries = $state<Record<string, TeacherPromptEntry>>({});
	// Per-cell working copy that mirrors the textarea content; separate from `entries`
	// so we can show a dirty indicator without re-fetching on every keystroke.
	let drafts = $state<Record<string, string>>({});
	let saving = $state<Record<string, boolean>>({});
	let errors = $state<Record<string, string | null>>({});
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	function cellKey(zone: string, kind: string) {
		return `${zone}:${kind}`;
	}

	onMount(() => {
		void load();
	});

	async function load() {
		loading = true;
		loadError = null;
		try {
			const list = await api.listTeacherPrompts();
			entries = {};
			drafts = {};
			for (const e of list) {
				const k = cellKey(e.zone, e.kind);
				entries[k] = e;
				drafts[k] = e.content;
			}
		} catch (e: unknown) {
			loadError =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Failed to load prompts';
		} finally {
			loading = false;
		}
	}

	function isDirty(zone: string, kind: string): boolean {
		const k = cellKey(zone, kind);
		return drafts[k] !== (entries[k]?.content ?? '');
	}

	async function save(zone: string, kind: string) {
		const k = cellKey(zone, kind);
		const content = (drafts[k] ?? '').trim();
		if (!content) {
			errors[k] = 'Prompt cannot be empty — use Reset to fall back to the default.';
			return;
		}
		saving[k] = true;
		errors[k] = null;
		try {
			const updated = await api.saveTeacherPrompt(zone, kind, content);
			entries[k] = updated;
			drafts[k] = updated.content;
		} catch (e: unknown) {
			errors[k] =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Save failed';
		} finally {
			saving[k] = false;
		}
	}

	async function reset(zone: string, kind: string) {
		const k = cellKey(zone, kind);
		if (!confirm(`Reset the ${zone} / ${kind} prompt to the built-in default? Your custom prompt will be discarded.`)) {
			return;
		}
		saving[k] = true;
		errors[k] = null;
		try {
			const updated = await api.resetTeacherPrompt(zone, kind);
			entries[k] = updated;
			drafts[k] = updated.content;
		} catch (e: unknown) {
			errors[k] =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Reset failed';
		} finally {
			saving[k] = false;
		}
	}

	function loadDefaultIntoDraft(zone: string, kind: string) {
		const k = cellKey(zone, kind);
		const e = entries[k];
		if (e) drafts[k] = e.default_content;
	}

	function formatUpdatedAt(iso: string | null): string {
		if (!iso) return '';
		try {
			return new Date(iso).toLocaleString('de-DE', {
				day: '2-digit', month: '2-digit', year: 'numeric',
				hour: '2-digit', minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}
</script>

<div class="border border-border bg-surface p-6">
	<h2 class="mb-1 font-semibold text-text">Teacher Prompts</h2>
	<p class="mb-4 text-sm text-text-muted">
		Edit the per-zone prompts the teacher uses for batch backfills, sample-detail Re-runs,
		and the Compare page. Chat prompts support <code class="bg-bg px-1 text-[11px]">{`{width}`}</code>
		and <code class="bg-bg px-1 text-[11px]">{`{height}`}</code> placeholders that are
		filled in per image. Perceptron uses a short native instruction — long chat-style
		text will pull it back into prose mode.
	</p>

	{#if loadError}
		<div class="mb-4 border border-warning-strong bg-warning-bg px-3 py-2 text-sm text-warning-strong">
			{loadError}
		</div>
	{/if}

	{#if loading}
		<div class="text-sm text-text-muted">Loading…</div>
	{:else}
		<div class="space-y-6">
			{#each ZONES as zone (zone.key)}
				<div class="border border-border bg-surface">
					<div class="border-b border-border px-4 py-2">
						<h3 class="text-sm font-semibold text-text">{zone.label}</h3>
						<div class="text-[11px] text-text-muted font-mono">{zone.key}</div>
					</div>
					<div class="divide-y divide-border">
						{#each KINDS as kind (kind.key)}
							{@const k = cellKey(zone.key, kind.key)}
							{@const entry = entries[k]}
							{@const dirty = isDirty(zone.key, kind.key)}
							<div class="p-4">
								<div class="mb-2 flex flex-wrap items-baseline justify-between gap-2">
									<div class="flex items-baseline gap-2">
										<span class="text-xs font-medium text-text">{kind.label}</span>
										{#if entry?.is_custom}
											<span class="border border-primary/30 bg-primary-light px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-primary">Custom</span>
										{:else}
											<span class="text-[10px] uppercase tracking-wider text-text-muted">Default</span>
										{/if}
									</div>
									{#if entry?.is_custom && entry?.updated_at}
										<div class="text-[10px] text-text-muted">
											Updated {formatUpdatedAt(entry.updated_at)}
											{#if entry.updated_by_display_name} by {entry.updated_by_display_name}{/if}
										</div>
									{/if}
								</div>

								<textarea
									bind:value={drafts[k]}
									rows={kind.key === 'perceptron' ? 4 : 14}
									class="block w-full border border-border bg-surface px-3 py-2 font-mono text-[11px] leading-relaxed text-text focus:border-primary focus:outline-none"
								></textarea>

								{#if errors[k]}
									<div class="mt-2 border border-warning-strong bg-warning-bg px-2 py-1 text-[11px] text-warning-strong">
										{errors[k]}
									</div>
								{/if}

								<div class="mt-2 flex flex-wrap items-center gap-2">
									<button
										type="button"
										onclick={() => save(zone.key, kind.key)}
										disabled={!dirty || saving[k]}
										class="border border-primary bg-primary px-3 py-1 text-xs font-medium text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
									>
										{saving[k] ? 'Saving…' : 'Save'}
									</button>
									<button
										type="button"
										onclick={() => loadDefaultIntoDraft(zone.key, kind.key)}
										disabled={saving[k]}
										class="border border-border bg-surface px-3 py-1 text-xs text-text hover:bg-bg disabled:opacity-40"
										title="Replace the textarea with the built-in default; doesn't save until you click Save."
									>
										Load default into editor
									</button>
									{#if entry?.is_custom}
										<button
											type="button"
											onclick={() => reset(zone.key, kind.key)}
											disabled={saving[k]}
											class="ml-auto border border-warning-strong bg-warning-bg px-3 py-1 text-xs text-warning-strong hover:bg-warning-bg/70 disabled:opacity-40"
											title="Drop the saved custom prompt; reverts to built-in default for new detections."
										>
											Reset to default
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Badge from '$lib/components/ui/Badge.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import RunColors from '$lib/components/training/RunColors.svelte';
	import ColorDropdown from '$lib/components/training/ColorDropdown.svelte';
	import RunButton from '$lib/components/training/RunButton.svelte';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import {
		binKey,
		binLabel,
		formatDuration,
		formatTime,
		formatWhen,
		getBinChoices,
		getTraining,
		saveTrainingConfig,
		type BinChoice,
		type TrainingBin,
		type TrainingMode,
		type TrainingState
	} from '$lib/training/api';

	const machine = getMachineContext();

	const POLL_MS = 3000;
	const MODES: { value: TrainingMode; label: string }[] = [{ value: 'color', label: 'Color' }];
	const NO_BIN = 'none';

	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());

	let training = $state<TrainingState | null>(null);
	let loadError = $state<string | null>(null);
	let saving = $state(false);
	let saveError = $state<string | null>(null);

	// The bins on enabled layers, for the fixed bin. The one set stays a
	// choice even when its layer is off.
	let bins = $state<BinChoice[]>([]);
	const fixedBin = $derived(training?.config.bin ?? null);
	const binOptions = $derived.by(() => {
		const options = bins.map((b) => ({ value: binKey(b), label: binLabel(b, bins) }));
		if (fixedBin && !bins.some((b) => binKey(b) === binKey(fixedBin))) {
			options.unshift({ value: binKey(fixedBin), label: binLabel(fixedBin) });
		}
		return [{ value: NO_BIN, label: 'None (route by the profile)' }, ...options];
	});

	function chooseBin(key: string) {
		const all: TrainingBin[] = fixedBin ? [fixedBin, ...bins] : bins;
		const chosen = all.find((b) => binKey(b) === key);
		void save({
			bin: chosen ? { layer: chosen.layer, section: chosen.section, bin: chosen.bin } : null
		});
	}

	$effect(() => {
		const from = base;
		void sortingProfileStore.load(from).catch(() => {});
		getBinChoices(from)
			.then((choices) => {
				if (from === base) bins = choices;
			})
			.catch(() => {
				if (from === base) bins = [];
			});
	});

	function message(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	async function load() {
		try {
			training = await getTraining(base);
			loadError = null;
		} catch (e) {
			loadError = `Couldn't load training mode: ${message(e)}`;
		}
	}

	async function save(change: {
		enabled?: boolean;
		mode?: TrainingMode;
		bin?: TrainingBin | null;
	}) {
		saving = true;
		saveError = null;
		try {
			training = await saveTrainingConfig(base, change);
		} catch (e) {
			saveError = message(e);
		} finally {
			saving = false;
		}
	}

	function open(event: MouseEvent, id: string) {
		// The date in the first cell is a link of its own.
		if ((event.target as HTMLElement).closest('a')) return;
		void goto(`/settings/data/training/${id}`);
	}

	onMount(() => {
		void load();
		const timer = setInterval(() => void load(), POLL_MS);
		return () => clearInterval(timer);
	});
</script>

<svelte:head><title>Sorter - Training runs</title></svelte:head>

<PageHeader
	title="Training runs"
	description="Runs that label every piece the machine sees with the colors you feed it, for training color recognition. The machine sorts as usual, and the runs go to Hive with the pieces."
/>

<Panel title="Training mode" flush>
	{#if !training}
		<div class="flex items-center gap-2 px-(--pad-panel) pb-4 text-sm text-ink-muted">
			{#if loadError}
				<span class="text-danger-ink">{loadError}</span>
			{:else}
				<Spinner size={14} /> Loading
			{/if}
		</div>
	{:else}
		<div class="divide-y divide-line">
			<SettingRow
				label="Training mode"
				help="While it is on, the dashboard shows the training run in place of Recent pieces. Turning it off ends the run."
			>
				<Switch
					checked={training.config.enabled}
					label="Training mode"
					disabled={saving}
					onchange={(on) => save({ enabled: on })}
				/>
			</SettingRow>

			<SettingRow label="Mode" help="What a run labels its pieces with." for="training-mode">
				<Select
					id="training-mode"
					value={training.config.mode}
					options={MODES}
					disabled={saving}
					onchange={(mode) => save({ mode })}
					class="w-40"
				/>
			</SettingRow>

			<SettingRow
				label="Bin"
				help="Every piece goes to this bin while training mode is on, and the chute stays there. None: pieces go where the sorting profile sends them."
				for="training-bin"
				changed={fixedBin !== null}
				defaultText="None"
				defaultHelp="Route pieces by the sorting profile again."
				onreset={() => save({ bin: null })}
			>
				<Select
					id="training-bin"
					value={fixedBin ? binKey(fixedBin) : NO_BIN}
					options={binOptions}
					disabled={saving}
					onchange={chooseBin}
					class="w-full sm:w-80"
				/>
			</SettingRow>

			<SettingRow
				label="Color"
				help="The color being fed. Picking another while a run is open starts a new segment of it, at once."
			>
				<ColorDropdown {base} {training} onsaved={(next) => (training = next)} />
			</SettingRow>

			<SettingRow
				label="Run"
				help={training.current_run
					? `Collecting since ${formatTime(training.current_run.started_at)}: ${training.current_run.pieces.toLocaleString()} pieces in ${training.current_run.segments.length} ${training.current_run.segments.length === 1 ? 'segment' : 'segments'}.`
					: 'A run collects every piece the machine sees until you end it, across pauses.'}
			>
				{#snippet tags()}
					{#if training?.current_run}<Badge tone="success" dot>Collecting</Badge>{/if}
				{/snippet}
				<RunButton {base} {training} onchange={(next) => (training = next)} />
			</SettingRow>

			{#if saveError}
				<p class="px-(--pad-panel) py-(--pad-row) text-sm text-danger-ink">{saveError}</p>
			{/if}
		</div>
	{/if}
</Panel>

<Panel
	title="Runs"
	description="Newest first. Open a run to see its pieces and exclude any that are wrong."
	flush
>
	{#if training && training.runs.length === 0}
		<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">
			No runs yet. Pick a color and start one above.
		</p>
	{:else if training}
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>Started</th>
						<th>Duration</th>
						<th>Colors</th>
						<th class="num">Pieces</th>
						<th class="num">Labeled</th>
						<th class="num">Excluded</th>
					</tr>
				</thead>
				<tbody>
					{#each training.runs as run (run.id)}
						<!-- The whole row opens the run; the link in its first cell is the
						     same for the keyboard. -->
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
						<tr class="is-link" onclick={(event) => open(event, run.id)}>
							<td>
								<span class="flex items-center gap-2 whitespace-nowrap">
									<a href="/settings/data/training/{run.id}" class="num text-ink">
										{formatWhen(run.started_at)}
									</a>
									{#if run.excluded}<Badge>Excluded</Badge>{/if}
								</span>
							</td>
							<td class="whitespace-nowrap">
								{#if run.ended_at === null}
									<Badge tone="success" dot>Collecting</Badge>
								{:else}
									<span class="num">{formatDuration(run.ended_at - run.started_at)}</span>
								{/if}
							</td>
							<td><RunColors colors={run.colors} /></td>
							<td class="num">{run.pieces.toLocaleString()}</td>
							<td class="num">{run.labeled.toLocaleString()}</td>
							<td class="num">{run.excluded_pieces.toLocaleString()}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</Panel>

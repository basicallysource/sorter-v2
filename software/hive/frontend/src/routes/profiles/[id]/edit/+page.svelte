<script lang="ts">
	import { afterNavigate, beforeNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import GitFork from '@lucide/svelte/icons/git-fork';
	import Layers from '@lucide/svelte/icons/layers';
	import Plus from '@lucide/svelte/icons/plus';
	import ToggleLeft from '@lucide/svelte/icons/toggle-left';
	import ToggleRight from '@lucide/svelte/icons/toggle-right';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';
	import {
		api,
		type ApiError,
		type Kit,
		type KitSummary,
		type ProfileHead,
		type ProfilePreview,
		type ProfileProblem,
		type SortingProfileDetail,
		type SortingProfileVersion
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { savedBy } from '$lib/profile-display';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import BinsResult from '$lib/components/profile/edit/BinsResult.svelte';
	import { catalog } from '$lib/components/profile/edit/catalog.svelte';
	import FallbackEditor from '$lib/components/profile/edit/FallbackEditor.svelte';
	import { emptyMessage, isMulti, valueKind } from '$lib/components/profile/edit/fields';
	import KitLines from '$lib/components/profile/edit/KitLines.svelte';
	import KitPicker from '$lib/components/profile/edit/KitPicker.svelte';
	import KitRuleEditor from '$lib/components/profile/edit/KitRuleEditor.svelte';
	import Matches from '$lib/components/profile/edit/Matches.svelte';
	import ProfileChatPanel from '$lib/components/profile/edit/ProfileChatPanel.svelte';
	import RuleEditor from '$lib/components/profile/edit/RuleEditor.svelte';
	import RuleList from '$lib/components/profile/edit/RuleList.svelte';
	import type { RowMark } from '$lib/components/profile/edit/RuleRow.svelte';
	import {
		allConditions,
		documentFor,
		duplicateRule,
		fallbackChoice,
		groupBy,
		groupProblems,
		isEmptyValue,
		isKitRule,
		isUnfinishedWarning,
		moveRule,
		newCondition,
		newKitRule,
		newRule,
		nextRuleName,
		normalizeRule,
		patchRule,
		plural,
		REST_ID,
		removeRule,
		reorderRule,
		replaceRule,
		topRuleIdFor,
		type Condition,
		type FallbackChoice,
		type Rule
	} from '$lib/components/profile/edit/rules';
	import SavePopover from '$lib/components/profile/edit/SavePopover.svelte';
	import VersionsPanel from '$lib/components/profile/edit/VersionsPanel.svelte';

	type RightTab = 'matches' | 'bins' | 'chat' | 'versions';
	type NarrowView = 'rules' | 'rule' | RightTab;

	const profileId = $derived(page.params.id ?? '');
	const isNewProfile = $derived(page.url.searchParams.get('new') === '1');
	const hasOpenRouter = $derived(Boolean(auth.user?.openrouter_configured));

	// --- The profile and the draft being edited -------------------------------------
	let loading = $state(true);
	let loadError = $state<string | null>(null);
	let profile = $state.raw<SortingProfileDetail | null>(null);

	// The draft: what the rules and the fallback are as edited here, unsaved.
	let rules = $state.raw<Rule[]>([]);
	let fallback = $state<FallbackChoice>('none');
	let defaultCategoryId = $state('misc');
	// The same, as last saved, for telling whether there is anything to save.
	let savedRules = $state.raw<Rule[]>([]);
	let savedKey = $state('');
	// The version number the draft started from.
	let baseVersion = $state(0);

	const draftKey = $derived(JSON.stringify([rules, fallback, defaultCategoryId]));
	const dirty = $derived(profile !== null && draftKey !== savedKey);
	// What every preview sees: the draft without the places still being made (a
	// condition with no field, or nothing chosen yet), so it shows the rule as far
	// as it is made. What a save sends keeps the conditions not yet finished, for
	// the server to say so.
	const draft = $derived(documentFor(profile?.name ?? '', rules, fallback, defaultCategoryId, true));
	const toSave = $derived(documentFor(profile?.name ?? '', rules, fallback, defaultCategoryId));
	const serverKey = $derived(JSON.stringify(draft));
	// What decides the parts a rule matches: its own conditions, not its name or
	// its place, so renaming does not ask for them again.
	const matchKey = $derived.by(() => {
		const rule = draft.rules.find((r) => r.id === selectedId);
		return rule ? JSON.stringify([rule.match_mode, rule.conditions, rule.children]) : '';
	});

	// --- Choosing ------------------------------------------------------------------------
	let selectedId = $state<string | null>(null);
	const selectedRule = $derived(rules.find((rule) => rule.id === selectedId) ?? null);
	let rightTab = $state<RightTab>('matches');
	// Below the width where three columns fit, one of them shows at a time.
	let narrow = $state<'rules' | 'rule' | 'result'>('rules');
	const narrowTab = $derived<NarrowView>(narrow === 'result' ? rightTab : narrow);

	function select(id: string | null) {
		selectedId = id;
		if (id !== null) narrow = 'rule';
	}

	// --- The live preview -----------------------------------------------------------------
	let preview = $state.raw<ProfilePreview | null>(null);
	let previewBusy = $state(false);
	let previewError = $state<string | null>(null);
	let previewSeq = 0;
	// Bumped when the page comes back into view, so a kit edited elsewhere shows.
	let comeback = $state(0);

	// A preview that fails (the server busy, say) is asked for again a few times.
	let previewTries = $state(0);
	let previewFailures = 0;

	$effect(() => {
		void serverKey;
		void comeback;
		void previewTries;
		if (!profile) return;
		const body = untrack(() => draft);
		const first = untrack(() => preview === null);
		const seq = ++previewSeq;
		previewBusy = true;
		let retry: ReturnType<typeof setTimeout> | undefined;
		const timer = setTimeout(
			async () => {
				try {
					const result = await api.previewSortingProfile(body);
					if (seq !== previewSeq) return;
					preview = result;
					previewError = null;
					previewFailures = 0;
					serverProblems = [];
					catalog.learn(result.categories);
				} catch {
					if (seq !== previewSeq) return;
					previewFailures += 1;
					if (previewFailures <= 3) {
						previewError = 'The preview could not be updated. It will try again in a moment.';
						retry = setTimeout(() => (previewTries += 1), 3000);
					} else {
						previewError = 'The preview could not be updated. Change something, or reload the page, to try again.';
					}
				}
				previewBusy = false;
			},
			first ? 0 : 300
		);
		return () => {
			clearTimeout(timer);
			clearTimeout(retry);
		};
	});

	// --- Problems and warnings ---------------------------------------------------------------
	// What the server said was wrong when a save was refused.
	let serverProblems = $state.raw<ProfileProblem[]>([]);
	// A save has been tried: from then on, every half-made condition says so.
	let attempted = $state(false);

	const problems = $derived(serverProblems.length > 0 ? serverProblems : (preview?.problems ?? []));
	const issues = $derived(groupProblems(problems));
	const warningsByRule = $derived(groupBy(preview?.warnings ?? [], (warning) => warning.rule_id));

	function problemFor(condition: Condition): string | null {
		// A value still to be chosen is what the row is waiting for, not a fault,
		// until a save is tried.
		if (isEmptyValue(condition.value)) {
			if (!attempted || !condition.field) return null;
			return emptyMessage(valueKind(catalog.fieldByKey(condition.field)), isMulti(condition.op));
		}
		const message = issues.byCondition[condition.id];
		if (!message) return null;
		// The server names the field first ("Name: ..."); the row already does.
		const label = catalog.fieldByKey(condition.field)?.label;
		return label && message.startsWith(`${label}: `) ? message.slice(label.length + 2) : message;
	}

	function problemsOf(rule: Rule): string[] {
		const out = [...(issues.byRule[rule.id] ?? [])];
		for (const condition of allConditions(rule)) {
			const message = problemFor(condition);
			if (message) out.push(message);
		}
		return out;
	}

	function warningsOf(id: string): string[] {
		return (warningsByRule[id] ?? [])
			.filter((warning) => attempted || !isUnfinishedWarning(warning))
			.map((warning) => warning.message);
	}

	const marks = $derived.by(() => {
		const out: Record<string, RowMark> = {};
		for (const rule of rules) {
			const wrong = problemsOf(rule);
			if (wrong.length > 0) {
				out[rule.id] = { tone: 'danger', text: wrong[0] };
				continue;
			}
			const odd = warningsOf(rule.id);
			if (odd.length > 0) out[rule.id] = { tone: 'warning', text: odd[0] };
		}
		return out;
	});

	// --- Loading ---------------------------------------------------------------------------------
	let loadedId = '';

	$effect(() => {
		const id = profileId;
		if (!id || id === loadedId) return;
		loadedId = id;
		untrack(() => void loadProfile());
	});

	async function loadProfile(options: { keepSelection?: boolean } = {}) {
		if (!profileId) return;
		if (!options.keepSelection) loading = true;
		loadError = null;
		try {
			// The fields come first: a saved rule may name one by an older name.
			const [detail] = await Promise.all([api.getSortingProfile(profileId), catalog.ensureFields()]);
			profile = detail;
			nameDraft = detail.name;
			hydrate(detail, options.keepSelection ?? false);
		} catch (e) {
			loadError = (e as ApiError)?.error ?? 'The profile could not be loaded.';
		} finally {
			loading = false;
		}
	}

	function hydrate(detail: SortingProfileDetail, keepSelection: boolean) {
		const version = detail.current_version;
		if (!version) return;
		const fresh = version.rules.map((rule) => normalizeRule(rule, catalog.aliases));
		rules = fresh;
		fallback = fallbackChoice(version.fallback_mode);
		defaultCategoryId = version.default_category_id || 'misc';
		savedRules = fresh;
		savedKey = JSON.stringify([fresh, fallback, defaultCategoryId]);
		baseVersion = version.version_number;
		headNotice = null;
		serverProblems = [];
		saveError = null;
		attempted = false;
		if (!keepSelection) preview = null;
		const asked = keepSelection ? null : requestedRule(fresh);
		if (asked) {
			selectedId = asked;
			narrow = 'rule';
		} else if (!keepSelection || !(selectedId === REST_ID || fresh.some((rule) => rule.id === selectedId))) {
			selectedId = fresh[0]?.id ?? null;
		}
	}

	// A link can ask for the rule to open: ?rule=RULE_ID, or ?rule=rest for the
	// fallback's "Everything else". A rule that is not there opens the first one.
	function requestedRule(list: Rule[]): string | null {
		const asked = page.url.searchParams.get('rule');
		return asked && (asked === REST_ID || list.some((rule) => rule.id === asked)) ? asked : null;
	}

	// The profile's name is edited in the header, apart from the rules.
	let nameDraft = $state('');

	async function renameProfile() {
		if (!profile) return;
		const name = nameDraft.trim();
		if (!name || name === profile.name) {
			nameDraft = profile.name;
			return;
		}
		try {
			profile = await api.updateSortingProfile(profile.id, { name });
		} catch {
			// The name stays as it was.
		}
		nameDraft = profile?.name ?? name;
	}

	// --- Changing the draft ---------------------------------------------------------------------
	function changeRule(next: Rule) {
		rules = replaceRule(rules, next.id, next);
	}

	function addRule() {
		const rule = { ...newRule(nextRuleName(rules)), conditions: [newCondition()] };
		rules = [...rules, rule];
		select(rule.id);
	}

	function toggleRule(id: string) {
		const rule = rules.find((r) => r.id === id);
		if (rule) rules = patchRule(rules, id, { disabled: !rule.disabled });
	}

	function duplicate(id: string) {
		const index = rules.findIndex((rule) => rule.id === id);
		if (index < 0) return;
		const copy = duplicateRule(rules[index]);
		rules = [...rules.slice(0, index + 1), copy, ...rules.slice(index + 1)];
		select(copy.id);
	}

	let deleting = $state<Rule | null>(null);

	function confirmDelete() {
		const rule = deleting;
		deleting = null;
		if (!rule) return;
		const index = rules.findIndex((r) => r.id === rule.id);
		rules = removeRule(rules, rule.id);
		if (selectedId === rule.id) selectedId = rules[Math.min(index, rules.length - 1)]?.id ?? null;
	}

	// A kit is chosen in a dialog: for a new kit rule, or to change a rule's kit.
	let choosingKitFor = $state<'new' | string | null>(null);

	function pickedKit(kit: Kit | KitSummary, open: boolean) {
		const target = choosingKitFor;
		choosingKitFor = null;
		if (target === 'new') {
			const rule = newKitRule(kit.name, kit.id);
			rules = [...rules, rule];
			select(rule.id);
		} else if (target) {
			rules = rules.map((rule) =>
				rule.id === target
					? {
							...rule,
							rule_type: 'kit' as const,
							kit_id: kit.id,
							set_source: undefined,
							set_num: undefined,
							set_meta: undefined,
							custom_parts: []
						}
					: rule
			);
		}
		comeback += 1;
		if (open) window.open(`/kits/${kit.id}`, '_blank', 'noopener');
	}

	// --- Saving ----------------------------------------------------------------------------------------
	let saving = $state(false);
	let saveOpen = $state(false);
	let saveError = $state<string | null>(null);
	let notice = $state<string | null>(null);

	async function save(note: string | null) {
		if (!profile || saving) return;
		saving = true;
		saveError = null;
		notice = null;
		attempted = true;
		try {
			const version = await api.saveSortingProfileVersion(profile.id, {
				name: profile.name,
				description: profile.description ?? null,
				default_category_id: defaultCategoryId,
				rules: toSave.rules,
				fallback_mode: toSave.fallback_mode,
				change_note: note
			});
			// This version is ours: the head check must not take it for someone else's.
			baseVersion = version.version_number;
			saveOpen = false;
			await loadProfile({ keepSelection: true });
			notice = `Saved version ${version.version_number}.`;
		} catch (e) {
			const failure = e as ApiError & { details?: ProfileProblem[] };
			saveOpen = false;
			if (failure.code === 'PROFILE_RULES_INVALID' && Array.isArray(failure.details)) {
				// Each problem goes where it belongs, on its rule and its condition.
				serverProblems = failure.details;
				const count = failure.details.length;
				saveError = `${count === 1 ? '1 problem keeps' : `${plural(count, 'problem')} keep`} this version from being saved. Each one is shown on its rule.`;
				const first = failure.details.map((p) => topRuleIdFor(rules, p)).find((id) => id !== null);
				if (first) select(first);
			} else {
				saveError = failure.error ?? 'The version could not be saved.';
			}
		} finally {
			saving = false;
		}
	}

	function onapplied(version: SortingProfileVersion) {
		baseVersion = version.version_number;
		void loadProfile({ keepSelection: true });
	}

	// --- Versions ---------------------------------------------------------------------------------------
	let restoringId = $state<string | null>(null);
	let askRestore = $state<string | null>(null);

	function restoreClicked(id: string) {
		if (dirty) askRestore = id;
		else void restore(id);
	}

	async function restore(id: string) {
		askRestore = null;
		if (!profile) return;
		restoringId = id;
		saveError = null;
		try {
			const old = (await api.getSortingProfile(profile.id, id)).current_version;
			if (!old) throw new Error('That version is gone.');
			const version = await api.saveSortingProfileVersion(profile.id, {
				name: old.name,
				description: old.description ?? null,
				default_category_id: old.default_category_id,
				rules: old.rules,
				fallback_mode: old.fallback_mode,
				change_note: `Restored from v${old.version_number}`
			});
			baseVersion = version.version_number;
			await loadProfile({ keepSelection: true });
			notice = `Restored version ${old.version_number} as version ${version.version_number}.`;
			rightTab = 'matches';
		} catch (e) {
			saveError = (e as ApiError)?.error ?? (e as Error)?.message ?? 'The version could not be restored.';
		} finally {
			restoringId = null;
		}
	}

	async function fork(versionId?: string) {
		if (!profile) return;
		saveError = null;
		try {
			const copy = await api.forkSortingProfile(profile.id, { add_to_library: true }, versionId);
			await goto(`/profiles/${copy.id}/edit`);
		} catch (e) {
			saveError = (e as ApiError)?.error ?? 'The profile could not be forked.';
		}
	}

	// --- Someone else saved meanwhile --------------------------------------------------------------------
	// An assistant saving through the API puts a newer version under the editor. The
	// head is cheap to ask for, so it is asked every few seconds while the tab shows.
	let headNotice = $state<ProfileHead | null>(null);
	let dismissedVersion = 0;
	let assistantBusy = $state(false);
	let confirmLoad = $state(false);

	async function checkHead() {
		if (!profile || saving || restoringId !== null || assistantBusy) return;
		if (document.visibilityState !== 'visible') return;
		try {
			const head = await api.getSortingProfileHead(profile.id);
			// A save of our own may have started while this was on its way; its
			// version is not someone else's.
			if (saving || restoringId !== null || assistantBusy) return;
			if (head.latest_version_number > baseVersion) {
				if (head.latest_version_number > dismissedVersion) headNotice = head;
			} else {
				headNotice = null;
			}
		} catch {
			// The next check will try again.
		}
	}

	$effect(() => {
		if (!profile?.is_owner) return;
		const timer = setInterval(() => void checkHead(), 5000);
		const shown = () => {
			if (document.visibilityState === 'visible') {
				comeback += 1;
				void checkHead();
			}
		};
		document.addEventListener('visibilitychange', shown);
		return () => {
			clearInterval(timer);
			document.removeEventListener('visibilitychange', shown);
		};
	});

	// "by Assistant (API key)", "by the editor's chat", "by Hive"; the editor itself
	// is another tab, since this one knows its own saves.
	function whoSaved(head: ProfileHead): string {
		if (head.created_via === 'web') return 'in another tab of the editor';
		return savedBy(head.created_via, head.created_via_key_name) ?? 'elsewhere';
	}

	function loadIt() {
		confirmLoad = false;
		notice = null;
		void loadProfile({ keepSelection: true });
	}

	// --- Leaving with unsaved changes --------------------------------------------------------------------
	// The move is stopped, and the dialog either carries it on to where it was
	// headed or stays here.
	let leaveTarget = $state<{ url: URL; delta: number | undefined } | null>(null);
	let leaveConfirmed = false;

	beforeNavigate((nav) => {
		if (leaveConfirmed || !dirty) return;
		// Closing the tab or leaving the site gets the browser's own prompt from cancel().
		nav.cancel();
		if (!nav.willUnload && nav.to) {
			leaveTarget = { url: nav.to.url, delta: nav.type === 'popstate' ? nav.delta : undefined };
		}
	});

	afterNavigate(() => {
		leaveConfirmed = false;
	});

	function leaveAnyway() {
		const target = leaveTarget;
		leaveTarget = null;
		if (!target) return;
		leaveConfirmed = true;
		if (target.delta) history.go(target.delta);
		else void goto(target.url);
	}

	function onkeydown(event: KeyboardEvent) {
		if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
			event.preventDefault();
			if (dirty && !saving) saveOpen = true;
		}
	}

	// --- What the columns say -------------------------------------------------------------------------------
	const restMeta = $derived(
		{
			none: 'All together',
			bl_category: 'By BrickLink category',
			rb_category: 'By Rebrickable category',
			color: 'By color'
		}[fallback]
	);
	// The bin for everything else, for how many parts it gets.
	const restBin = $derived.by(() => {
		if (!preview) return null;
		const id = preview.category_order.find((key) => preview?.categories[key]?.kind === 'default');
		return id ? preview.categories[id] : null;
	});

	const tabs = $derived([
		{ value: 'matches' as const, label: 'Matches' },
		{ value: 'bins' as const, label: 'Categories' },
		{ value: 'chat' as const, label: 'Assistant' },
		{ value: 'versions' as const, label: 'Versions', count: profile?.versions.length }
	]);
	const narrowTabs = $derived([
		{ value: 'rules' as const, label: 'Rules' },
		{ value: 'rule' as const, label: 'Rule' },
		...tabs
	]);

	function chooseNarrow(view: NarrowView) {
		if (view === 'rules' || view === 'rule') narrow = view;
		else {
			narrow = 'result';
			rightTab = view;
		}
	}

	$effect(() => {
		void catalog.ensureFields();
	});
</script>

<svelte:head>
	<title>{profile ? `Edit ${profile.name} - Hive` : 'Edit profile - Hive'}</title>
</svelte:head>

<svelte:window {onkeydown} />

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if loadError}
	<Alert tone="danger">{loadError}</Alert>
{:else if !profile}
	<Alert tone="danger">Profile not found.</Alert>
{:else if !profile.current_version}
	<Alert tone="danger">This profile has no version to edit.</Alert>
{:else if !profile.is_owner}
	<Alert tone="info" title="Only the owner can edit this profile">
		Fork it to get a copy of your own to change.
		{#snippet actions()}
			<Button href="/profiles/{profileId}" size="sm">Back to the profile</Button>
			<Button variant="primary" size="sm" icon={GitFork} onclick={() => void fork()}>Fork it</Button>
		{/snippet}
	</Alert>
{:else}
	<div class="flex min-h-0 flex-col gap-(--gap-panels) xl:h-[calc(100dvh-var(--size-topbar)-3rem)]">
		<header class="flex items-center justify-between gap-3">
			<div class="flex min-w-0 flex-1 items-center gap-2">
				<Button href="/profiles/{profile.id}" variant="ghost" size="sm" icon={ArrowLeft} label="Back to the profile" />
				<!-- The hidden span sizes the grid cell, so the field hugs the name. -->
				<div class="inline-grid max-w-full min-w-0 items-center overflow-hidden">
					<span
						aria-hidden="true"
						class="invisible col-start-1 row-start-1 px-1.5 text-xl font-semibold whitespace-pre"
						>{nameDraft || 'Untitled profile'}</span
					>
					<input
						type="text"
						size="1"
						aria-label="Profile name"
						bind:value={nameDraft}
						onblur={renameProfile}
						onkeydown={(e) => {
							if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
						}}
						class="col-start-1 row-start-1 w-full min-w-0 rounded-control bg-transparent px-1.5 text-xl font-semibold text-ellipsis text-ink hover:bg-hover focus:bg-hover focus-visible:-outline-offset-2"
					/>
				</div>
				<Badge><span class="num">v{profile.current_version.version_number}</span></Badge>
			</div>
			<div class="flex shrink-0 items-center gap-3">
				{#if dirty}<span class="max-sm:hidden"><Badge tone="warning" dot>Unsaved changes</Badge></span>{/if}
				<SavePopover
					bind:open={saveOpen}
					profileId={profile.id}
					{hasOpenRouter}
					{savedRules}
					draftRules={toSave.rules}
					{dirty}
					{saving}
					onsave={save}
				/>
			</div>
		</header>

		{#if saveError}
			<Alert tone="danger">
				{saveError}
				{#snippet actions()}
					<Button variant="ghost" size="sm" icon={X} label="Dismiss" onclick={() => (saveError = null)} />
				{/snippet}
			</Alert>
		{/if}
		{#if notice}
			<Alert tone="success">
				{notice}
				{#snippet actions()}
					<Button variant="ghost" size="sm" icon={X} label="Dismiss" onclick={() => (notice = null)} />
				{/snippet}
			</Alert>
		{/if}
		{#if headNotice}
			<Alert tone="info" title="Version {headNotice.latest_version_number} was saved {whoSaved(headNotice)}">
				{dirty ? 'Load it to see it, and your unsaved changes are replaced. Or keep editing.' : 'Load it to see what changed, or keep editing.'}
				{#snippet actions()}
					<Button
						size="sm"
						onclick={() => {
							dismissedVersion = headNotice?.latest_version_number ?? 0;
							headNotice = null;
						}}>Keep editing</Button
					>
					<Button
						variant="primary"
						size="sm"
						onclick={() => (dirty ? (confirmLoad = true) : loadIt())}>Load it</Button
					>
				{/snippet}
			</Alert>
		{/if}

		<!-- Below the width where three columns fit, one shows at a time. -->
		<div class="overflow-hidden rounded-panel bg-surface xl:hidden">
			<Tabs label="Parts of the editor" inset value={narrowTab} items={narrowTabs} onchange={chooseNarrow} />
		</div>

		<!-- A chat needs room to read: with the assistant open, its column grows with the window. -->
		<div
			class="grid min-h-0 flex-1 gap-(--gap-panels) {rightTab === 'chat'
				? 'xl:grid-cols-[19rem_minmax(0,1fr)_minmax(25rem,0.9fr)]'
				: 'xl:grid-cols-[19rem_minmax(0,1fr)_25rem]'}"
		>
			<!-- The bins, in the order a piece meets them. -->
			<Panel
				title="Rules"
				flush
				fill
				class="min-w-0 {narrow === 'rules' ? '' : 'max-xl:hidden'}"
			>
				<RuleList
					{rules}
					bins={preview?.categories ?? {}}
					{marks}
					{selectedId}
					restName="Everything else"
					{restMeta}
					onselect={select}
					onmove={(id, delta) => (rules = moveRule(rules, id, delta))}
					onreorder={(id, slot) => (rules = reorderRule(rules, id, slot))}
					ontoggle={toggleRule}
					onduplicate={duplicate}
					ondelete={(id) => (deleting = rules.find((rule) => rule.id === id) ?? null)}
				/>
				{#snippet actions()}
					<Button size="sm" icon={Plus} onclick={addRule}>Add rule</Button>
					<Button size="sm" icon={Plus} onclick={() => (choosingKitFor = 'new')}>Add kit</Button>
				{/snippet}
			</Panel>

			<!-- The chosen rule, edited. -->
			<Panel
				title={selectedId === REST_ID ? 'Everything else' : selectedRule ? (isKitRule(selectedRule) ? 'Kit' : 'Rule') : 'Rule'}
				fill
				class="min-w-0 {narrow === 'rule' ? '' : 'max-xl:hidden'}"
			>
				{#snippet actions()}
					{#if selectedRule}
						{@const place = rules.findIndex((rule) => rule.id === selectedRule!.id)}
						<Button
							variant="ghost"
							size="sm"
							icon={ArrowUp}
							label="Move up"
							disabled={place <= 0}
							onclick={() => (rules = moveRule(rules, selectedRule!.id, -1))}
						/>
						<Button
							variant="ghost"
							size="sm"
							icon={ArrowDown}
							label="Move down"
							disabled={place === rules.length - 1}
							onclick={() => (rules = moveRule(rules, selectedRule!.id, 1))}
						/>
						<Button
							variant="ghost"
							size="sm"
							icon={selectedRule.disabled ? ToggleRight : ToggleLeft}
							onclick={() => toggleRule(selectedRule!.id)}
						>
							{selectedRule.disabled ? 'Turn on' : 'Turn off'}
						</Button>
						<Button
							variant="ghost"
							size="sm"
							icon={Trash2}
							label="Delete {selectedRule.name}"
							onclick={() => (deleting = selectedRule)}
						/>
					{/if}
				{/snippet}

				{#if selectedId === REST_ID}
					<FallbackEditor
						choice={fallback}
						requires={preview?.requires ?? []}
						restParts={restBin?.part_count ?? null}
						onchange={(choice) => (fallback = choice)}
					/>
				{:else if selectedRule}
					{#key selectedRule.id}
						{#if isKitRule(selectedRule)}
							<KitRuleEditor
								rule={selectedRule}
								bin={preview?.categories[selectedRule.id]}
								imageUrl={preview?.categories[selectedRule.id]?.image_url ?? selectedRule.image_url ?? null}
								warnings={warningsOf(selectedRule.id)}
								ruleProblems={issues.byRule[selectedRule.id] ?? []}
								reloadKey={comeback}
								onchange={changeRule}
								ontoggle={() => toggleRule(selectedRule!.id)}
								onchoosekit={() => (choosingKitFor = selectedRule!.id)}
							/>
						{:else}
							<RuleEditor
								rule={selectedRule}
								imageUrl={preview?.categories[selectedRule.id]?.image_url ?? selectedRule.image_url ?? null}
								warnings={warningsOf(selectedRule.id)}
								ruleProblems={issues.byRule[selectedRule.id] ?? []}
								{problemFor}
								{draft}
								onchange={changeRule}
								ontoggle={() => toggleRule(selectedRule!.id)}
							/>
						{/if}
					{/key}
				{:else}
					<EmptyState icon={Layers} title="No rules yet">
						A rule takes the parts that match its conditions. A kit collects the parts of a LEGO set or a
						list until it is full.
						{#snippet action()}
							<div class="flex flex-wrap justify-center gap-2">
								<Button variant="primary" icon={Plus} onclick={addRule}>Add rule</Button>
								<Button icon={Plus} onclick={() => (choosingKitFor = 'new')}>Add kit</Button>
							</div>
						{/snippet}
					</EmptyState>
				{/if}
			</Panel>

			<!-- What the draft does. -->
			<section
				class="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-panel bg-surface {narrow === 'result'
					? ''
					: 'max-xl:hidden'}"
			>
				<div class="max-xl:hidden">
					<Tabs label="Results and assistant" inset bind:value={rightTab} items={tabs} />
				</div>
				<div class="min-h-0 flex-1 overflow-y-auto {rightTab === 'chat' ? 'hidden' : ''}">
					{#if rightTab === 'matches'}
						{#if selectedRule && isKitRule(selectedRule)}
							<KitLines rule={selectedRule} reloadKey={comeback} />
						{:else if selectedRule}
							{#key selectedRule.id}
								<Matches {draft} draftKey={matchKey} ruleId={selectedRule.id} bin={preview?.categories[selectedRule.id]} />
							{/key}
						{:else}
							<p class="p-(--pad-panel) text-sm text-ink-muted">
								{selectedId === REST_ID
									? 'This bin takes what no rule takes. The Bins tab shows every bin.'
									: rules.length === 0
										? 'Add a rule to see the parts that match it.'
										: 'Choose a rule to see the parts that match it.'}
							</p>
						{/if}
					{:else if rightTab === 'bins'}
						<BinsResult
							{preview}
							busy={previewBusy}
							{draft}
							draftKey={serverKey}
							{rules}
							{selectedId}
							warningsFor={warningsOf}
							onselect={(id) => {
								select(id);
								rightTab = 'matches';
							}}
						/>
						{#if previewError}
							<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="warning">{previewError}</Alert></div>
						{/if}
					{:else if rightTab === 'versions'}
						<VersionsPanel {profile} {restoringId} onrestore={restoreClicked} onfork={(id) => void fork(id)} />
					{/if}
				</div>
				<ProfileChatPanel
					{profile}
					selectedRuleId={selectedId === REST_ID ? null : selectedId}
					{hasOpenRouter}
					{isNewProfile}
					rulesCount={rules.length}
					{dirty}
					active={rightTab === 'chat'}
					onbusy={(busy) => (assistantBusy = busy)}
					{onapplied}
				/>
			</section>
		</div>
	</div>
{/if}

<Modal open={deleting !== null} title="Delete this rule?" size="sm" onclose={() => (deleting = null)}>
	<p class="text-sm text-ink">
		"{deleting?.name}" is taken out of the draft, and the pieces it took go to the next rule that takes them.
	</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (deleting = null)}>Keep it</Button>
		<Button variant="danger" icon={Trash2} onclick={confirmDelete}>Delete rule</Button>
	{/snippet}
</Modal>

<Modal open={choosingKitFor !== null} title="Choose a kit" size="lg" onclose={() => (choosingKitFor = null)}>
	{#if choosingKitFor !== null}
		<KitPicker onpick={pickedKit} />
	{/if}
</Modal>

<Modal open={askRestore !== null} title="Restore this version?" size="sm" onclose={() => (askRestore = null)}>
	<p class="text-sm text-ink">
		Restoring saves that version as the newest one, and the changes you have not saved are replaced.
	</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (askRestore = null)}>Cancel</Button>
		<Button variant="primary" onclick={() => askRestore && void restore(askRestore)}>Restore</Button>
	{/snippet}
</Modal>

<Modal open={confirmLoad} title="Load the newer version?" size="sm" onclose={() => (confirmLoad = false)}>
	<p class="text-sm text-ink">Loading it replaces the changes you have not saved.</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (confirmLoad = false)}>Keep editing</Button>
		<Button variant="danger" onclick={loadIt}>Load it</Button>
	{/snippet}
</Modal>

<Modal open={leaveTarget !== null} title="Leave without saving?" size="sm" onclose={() => (leaveTarget = null)}>
	<p class="text-sm text-ink">This profile has changes that are not saved. If you leave now, they are lost.</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (leaveTarget = null)}>Stay</Button>
		<Button variant="danger" onclick={leaveAnyway}>Leave without saving</Button>
	{/snippet}
</Modal>

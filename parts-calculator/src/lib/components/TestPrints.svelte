<script lang="ts">
	import { onMount } from 'svelte';
	import { create, fromJson, toJson, type JsonValue } from '@bufbuild/protobuf';
	import { Code, ConnectError } from '@connectrpc/connect';
	import { admin, tests, requestID } from '$lib/test-prints';
	import { AssetSchema, TestCaseSchema, OnshapeReferenceSchema, SaveTestRequestSchema, type Board, type GetSessionResponse, type GetTestResponse, type SaveTestRequest, type TestCase } from '$lib/gen/testprints/v1/testprints_pb';

	let { editing = false } = $props<{ editing?: boolean }>();
	let session = $state<GetSessionResponse>();
	let boards = $state<Board[]>([]);
	let items = $state<TestCase[]>([]);
	let selected = $state<TestCase>();
	let detail = $state<GetTestResponse>();
	let references = $state('[]');
	let next_id = $state('');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let pending = $state<SaveTestRequest>();
	const may_edit = $derived(editing && session?.admin);
	const pinned = $derived(selected?.id !== '' && selected?.state !== 'draft');

	onMount(async () => {
		try {
			session = await tests.getSession({});
			if (session.signedIn && (!editing || session.admin)) {
				if (editing) boards = (await admin.listBoards({})).boards;
				await loadTests();
				const id = new URL(location.href).searchParams.get('id');
				if (id) await selectTest(id);
			}
		} catch { error = 'Test prints are not available on this host yet.'; }
	});

	async function loadTests(after_id = '') {
		const result = await tests.listTests({ includeDrafts: editing, afterId: after_id, limit: 50 });
		items = after_id ? [...items, ...result.tests] : result.tests;
		next_id = result.nextAfterId;
	}

	async function selectTest(id: string) {
		if (pending) return;
		busy = true; error = ''; notice = '';
		try {
			detail = await tests.getTest({ id });
			selected = detail.test;
			references = JSON.stringify(selected?.references.map((ref) => toJson(OnshapeReferenceSchema, ref)), null, 2);
		} catch (err) { error = ConnectError.from(err).rawMessage; }
		finally { busy = false; }
	}

	function newTest() {
		selected = create(TestCaseSchema, { kind: 'part', state: 'draft', boardId: boards[0]?.id ?? '' });
		detail = undefined; references = '[]'; error = ''; notice = '';
	}

	async function saveTest() {
		if (!selected) return;
		busy = true; error = ''; notice = '';
		try {
			if (!pending) {
				const refs: JsonValue = JSON.parse(references);
				if (!Array.isArray(refs)) throw new Error('References must be a JSON list.');
				selected.references = refs.map((ref) => fromJson(OnshapeReferenceSchema, ref));
				pending = create(SaveTestRequestSchema, { requestId: requestID(), expectedRevision: selected.revision, test: selected });
			}
			const result = await admin.saveTest(pending);
			selected = result.test; pending = undefined; notice = 'Saved.';
			await loadTests();
		} catch (err) {
			const failure = ConnectError.from(err);
			error = failure.rawMessage;
			if ([Code.InvalidArgument, Code.PermissionDenied, Code.Unauthenticated, Code.Aborted, Code.FailedPrecondition].includes(failure.code)) pending = undefined;
		} finally { busy = false; }
	}

	async function uploadFile(event: Event) {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file || !selected?.id) return;
		const types: Record<string, string> = { stl: 'model/stl', step: 'model/step', stp: 'model/step', '3mf': 'model/3mf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp' };
		busy = true; error = '';
		try {
			const response = await fetch(`/api/test-print-assets/${selected.id}?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file, headers: { 'Content-Type': types[file.name.split('.').pop()?.toLowerCase() ?? ''] ?? 'application/octet-stream' } });
			const body = await response.json();
			if (!response.ok) throw new Error(body.message ?? 'Upload failed.');
			const asset = fromJson(AssetSchema, body);
			if (!selected.assets.some((item) => item.id === asset.id)) selected.assets = [...selected.assets, asset];
			notice = 'Uploaded. Save the draft to attach this file.';
		} catch (err) { error = err instanceof Error ? err.message : 'Upload failed.'; }
		finally { busy = false; input.value = ''; }
	}

	async function downloadAsset(id: string) {
		if (!selected) return;
		try { const result = await tests.getDownload({ testId: selected.id, assetId: id }); location.assign(result.url); }
		catch (err) { error = ConnectError.from(err).rawMessage; }
	}

	async function moreFeedback() {
		if (!detail?.test || !detail.nextFeedbackAfterId) return;
		try {
			const result = await tests.getTest({ id: detail.test.id, feedbackAfterId: detail.nextFeedbackAfterId });
			detail.feedback = [...detail.feedback, ...result.feedback]; detail.nextFeedbackAfterId = result.nextFeedbackAfterId;
		} catch (err) { error = ConnectError.from(err).rawMessage; }
	}
</script>

<main class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
	<p class="text-sm text-text-muted">Private preview</p>
	<h1 class="mb-2 text-3xl font-bold">{editing ? 'Manage test prints' : 'Test prints & assemblies'}</h1>
	<p class="mb-6 text-text-muted">A specific version, a clear test, and feedback from the people building it.</p>
	{#if error}<p role="alert" class="mb-4 border border-red-400 p-3">{error}</p>{/if}
	{#if notice}<p role="status" class="mb-4 border border-border p-3">{notice}</p>{/if}
	{#if !session && !error}<p>Loading…</p>
	{:else if session && !session.signedIn}<a class="underline" href="/auth/signin?dest=/test-prints">Sign in to view test prints</a>
	{:else if editing && session && !session.admin}<p>Admin access requires membership in basically-core.</p>
	{:else if session?.signedIn}
		<div class="mb-6 flex gap-4 text-sm"><span>Signed in as {session.handle}</span><form method="POST" action="/auth/signout"><button class="underline">Sign out</button></form>{#if session.admin}<a class="underline" href={editing ? '/test-prints' : '/admin'}>{editing ? 'View tests' : 'Manage tests'}</a>{/if}</div>
		<div class="grid gap-8 md:grid-cols-[16rem_1fr]">
			<aside>
				{#if may_edit}<button class="mb-4 w-full border border-border p-3 text-left font-semibold" disabled={busy || !!pending || !boards.length} onclick={newTest}>+ New test</button>{/if}
				{#if !items.length}<p class="text-text-muted">No tests yet.</p>{/if}
				{#each items as item (item.id)}<button class="mb-2 block w-full border border-border p-3 text-left hover:border-primary" aria-pressed={selected?.id === item.id} disabled={busy || !!pending} onclick={() => selectTest(item.id)}><span class="block font-semibold">{item.title}</span><span class="text-sm text-text-muted">{item.kind} · {item.state}</span></button>{/each}
				{#if next_id}<button class="underline" onclick={() => loadTests(next_id).catch(() => error = 'Could not load more tests.')}>Load more</button>{/if}
			</aside>
			<section>
				{#if selected}
					{#if may_edit}
						<form onsubmit={(event) => { event.preventDefault(); saveTest(); }}>
							<fieldset disabled={busy || !!pending} class="grid gap-4 disabled:opacity-60">
								<label>Title<input class="mt-1 block w-full border border-border bg-surface p-2" required maxlength="160" bind:value={selected.title} /></label>
								<label>What to test<textarea class="mt-1 block w-full border border-border bg-surface p-2" rows="5" maxlength="12000" bind:value={selected.instructions}></textarea></label>
								<div class="flex flex-wrap gap-4">
									<label>Kind<select class="ml-2 border border-border bg-surface p-2" disabled={pinned} bind:value={selected.kind}><option>part</option><option>assembly</option><option>document</option></select></label>
									<label>Board<select class="ml-2 border border-border bg-surface p-2" disabled={pinned} bind:value={selected.boardId}>{#each boards as board}<option value={board.id}>{board.id} ({board.audience})</option>{/each}</select></label>
									<label>State<select class="ml-2 border border-border bg-surface p-2" disabled={!selected.id} bind:value={selected.state}><option>draft</option><option>open</option><option>closed</option><option>archived</option></select></label>
								</div>
								<label>Onshape references<textarea class="mt-1 block w-full border border-border bg-surface p-2 font-mono text-sm" rows="7" readonly={pinned} bind:value={references} spellcheck="false"></textarea><span class="text-sm text-text-muted">JSON list with documentId, versionId, elementId, optional partId and label. Use a version, not a workspace. Published targets stay fixed.</span></label>
								{#if selected.id && !pinned}<label>Add model or image (up to 32 MB)<input class="mt-2 block" type="file" accept=".stl,.step,.stp,.3mf,.png,.jpg,.jpeg,.webp" onchange={uploadFile} /></label>{/if}
							</fieldset>
							<button class="my-4 border border-primary px-5 py-2 font-semibold" disabled={busy}>{busy ? 'Working…' : pending ? 'Retry same save' : 'Save test'}</button>
							{#if pending}<p class="text-sm">Waiting for a confirmed save. Retry uses the same request to avoid creating a duplicate.</p>{/if}
						</form>
					{:else}<h2 class="mb-2 text-2xl font-bold">{selected.title}</h2><p class="mb-4 whitespace-pre-wrap">{selected.instructions}</p><p>{selected.kind} · {selected.state}</p>{/if}
					<ul class="my-4 space-y-2">{#each selected.references as ref}<li><a class="underline" href={`https://cad.onshape.com/documents/${ref.documentId}/v/${ref.versionId}/e/${ref.elementId}`} target="_blank" rel="noreferrer">{ref.label || 'View pinned CAD version'}</a>{#if ref.partId}<span class="ml-2 text-sm">Part {ref.partId}</span>{/if}</li>{/each}</ul>
					{#each selected.assets as asset}<button class="mr-4 underline" onclick={() => downloadAsset(asset.id)}>{asset.filename}</button>{/each}
					{#if selected.id}<p class="my-4 text-sm text-text-muted">Revision {String(selected.revision)} · {selected.claimCount} claims · {selected.feedbackCount} feedback entries</p>{/if}
					{#if detail}
						{#if detail.claims.length}<h3 class="mt-6 font-bold">Claimed by</h3><p>{detail.claims.map((claim) => claim.displayName).join(', ')}</p>{/if}
						<h3 class="mt-6 font-bold">Feedback</h3>
						{#each detail.feedback as feedback}<article class="my-3 border border-border p-4"><p class="font-semibold">{feedback.displayName}</p><p class="my-2 whitespace-pre-wrap">{feedback.body}</p>{#each feedback.assets as asset}<button class="mr-3 underline" onclick={() => downloadAsset(asset.id)}>{asset.filename}</button>{/each}<a class="block text-sm underline" href={feedback.discordUrl} target="_blank" rel="noreferrer">View in Discord</a></article>{/each}
						{#if detail.nextFeedbackAfterId}<button class="underline" onclick={moreFeedback}>More feedback</button>{/if}
					{/if}
				{:else}<p class="text-text-muted">Select a test to view its files and feedback.</p>{/if}
			</section>
		</div>
	{/if}
</main>

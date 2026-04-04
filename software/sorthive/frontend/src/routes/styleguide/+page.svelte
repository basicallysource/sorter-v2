<svelte:head>
	<title>Style Guide - SortHive</title>
</svelte:head>

<div class="space-y-16 pb-20">
	<!-- Header -->
	<div>
		<h1 class="text-3xl font-bold tracking-tight">Style Guide</h1>
		<p class="mt-1 text-sm text-[#7A7770]">SortHive Design System — "Precision Play"</p>
	</div>

	<!-- ─── Color Palette ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Color Palette</h2>
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
			<div>
				<div class="h-20 w-full border border-[#E2E0DB] bg-[#D01012]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Red</p>
				<p class="font-mono text-xs text-[#7A7770]">#D01012</p>
				<p class="text-xs text-[#7A7770]">Primary / CTA</p>
			</div>
			<div>
				<div class="h-20 w-full border border-[#E2E0DB] bg-[#0055BF]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Blue</p>
				<p class="font-mono text-xs text-[#7A7770]">#0055BF</p>
				<p class="text-xs text-[#7A7770]">Info / Selection</p>
			</div>
			<div>
				<div class="h-20 w-full border border-[#E2E0DB] bg-[#00852B]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Green</p>
				<p class="font-mono text-xs text-[#7A7770]">#00852B</p>
				<p class="text-xs text-[#7A7770]">Success / Connected</p>
			</div>
			<div>
				<div class="h-20 w-full border border-[#E2E0DB] bg-[#FFD500]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Yellow</p>
				<p class="font-mono text-xs text-[#7A7770]">#FFD500</p>
				<p class="text-xs text-[#7A7770]">Warning / Highlight</p>
			</div>
			<div>
				<div class="h-20 w-full border border-[#E2E0DB] bg-[#9B1D20]"></div>
				<p class="mt-2 text-xs font-medium">Dark Red</p>
				<p class="font-mono text-xs text-[#7A7770]">#9B1D20</p>
				<p class="text-xs text-[#7A7770]">Danger / Destructive</p>
			</div>
			<div>
				<div class="h-20 w-full border border-[#E2E0DB] bg-[#B00E10]"></div>
				<p class="mt-2 text-xs font-medium">Red Hover</p>
				<p class="font-mono text-xs text-[#7A7770]">#B00E10</p>
				<p class="text-xs text-[#7A7770]">Primary hover</p>
			</div>
		</div>
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-5">
			<div>
				<div class="h-16 w-full border border-[#E2E0DB] bg-[#F7F6F3]"></div>
				<p class="mt-2 text-xs font-medium">Background</p>
				<p class="font-mono text-xs text-[#7A7770]">#F7F6F3</p>
			</div>
			<div>
				<div class="h-16 w-full border border-[#E2E0DB] bg-white"></div>
				<p class="mt-2 text-xs font-medium">Surface</p>
				<p class="font-mono text-xs text-[#7A7770]">#FFFFFF</p>
			</div>
			<div>
				<div class="h-16 w-full border border-[#E2E0DB] bg-[#E2E0DB]"></div>
				<p class="mt-2 text-xs font-medium">Border</p>
				<p class="font-mono text-xs text-[#7A7770]">#E2E0DB</p>
			</div>
			<div>
				<div class="h-16 w-full border border-[#E2E0DB] bg-[#1A1A1A]"></div>
				<p class="mt-2 text-xs font-medium text-[#1A1A1A]">Text</p>
				<p class="font-mono text-xs text-[#7A7770]">#1A1A1A</p>
			</div>
			<div>
				<div class="h-16 w-full border border-[#E2E0DB] bg-[#7A7770]"></div>
				<p class="mt-2 text-xs font-medium">Text Muted</p>
				<p class="font-mono text-xs text-[#7A7770]">#7A7770</p>
			</div>
		</div>
	</section>

	<!-- ─── Typography ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Typography</h2>
		<div class="space-y-6 border border-[#E2E0DB] bg-white p-6">
			<div>
				<p class="text-xs uppercase tracking-wider text-[#7A7770]">IBM Plex Sans</p>
				<p class="mt-2 text-3xl font-bold tracking-tight">Page Title — 3xl Bold</p>
				<p class="mt-2 text-2xl font-bold">Section Header — 2xl Bold</p>
				<p class="mt-2 text-lg font-semibold">Subsection — lg Semibold</p>
				<p class="mt-2 text-sm font-medium">Label / Button — sm Medium</p>
				<p class="mt-2 text-sm">Body text — sm Regular. The quick brown fox jumps over the lazy dog.</p>
				<p class="mt-2 text-xs text-[#7A7770]">Caption / Timestamp — xs Muted</p>
			</div>
			<div class="border-t border-[#E2E0DB] pt-4">
				<p class="text-xs uppercase tracking-wider text-[#7A7770]">IBM Plex Mono</p>
				<p class="mt-2 font-mono text-2xl font-bold">1,636</p>
				<p class="mt-1 font-mono text-sm">part_num: 3023 | color_id: 15 | qty: 4</p>
				<p class="mt-1 font-mono text-xs text-[#7A7770]">75460-1 · 2026 · 558 parts</p>
			</div>
		</div>
	</section>

	<!-- ─── Buttons ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Buttons</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="flex flex-wrap items-center gap-3">
				<button class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]">Primary Action</button>
				<button class="border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Secondary</button>
				<button class="bg-[#9B1D20] px-4 py-2 text-sm font-medium text-white hover:bg-[#7A1517]">Danger</button>
				<button class="px-4 py-2 text-sm font-medium text-[#D01012] hover:bg-[#FEF2F2]">Ghost</button>
				<button class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white opacity-50" disabled>Disabled</button>
			</div>
			<div class="mt-4 flex flex-wrap items-center gap-3">
				<button class="bg-[#D01012] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#B00E10]">Small Primary</button>
				<button class="border border-[#E2E0DB] bg-white px-3 py-1.5 text-xs font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Small Secondary</button>
				<button class="text-xs font-medium text-[#9B1D20] hover:text-[#7A1517]">Small Destructive Text</button>
			</div>
		</div>
	</section>

	<!-- ─── Form Elements ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Form Elements</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="grid max-w-lg gap-4">
				<div>
					<label for="sg-text" class="mb-1 block text-sm font-medium">Text Input</label>
					<input id="sg-text" type="text" placeholder="Enter value..." class="w-full border border-[#E2E0DB] bg-white px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
				</div>
				<div>
					<label for="sg-search" class="mb-1 block text-sm font-medium">Search</label>
					<div class="flex gap-2">
						<input id="sg-search" type="search" placeholder="Search by name or set number..." class="flex-1 border border-[#E2E0DB] bg-white px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
						<button class="border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Search</button>
					</div>
				</div>
				<div class="flex items-center gap-2">
					<input id="sg-check" type="checkbox" class="h-4 w-4 accent-[#D01012]" />
					<label for="sg-check" class="text-sm">Include spare parts</label>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Badges ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Badges & Tags</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="flex flex-wrap items-center gap-3">
				<span class="border border-[#00852B]/30 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-[#00852B]">Published</span>
				<span class="border border-[#0055BF]/30 bg-sky-50 px-2.5 py-0.5 text-xs font-medium text-[#0055BF]">In Review</span>
				<span class="border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800">Warning</span>
				<span class="border border-[#D01012]/30 bg-[#FEF2F2] px-2.5 py-0.5 text-xs font-medium text-[#9B1D20]">Rejected</span>
				<span class="border border-[#E2E0DB] bg-[#F7F6F3] px-2.5 py-0.5 text-xs font-medium text-[#7A7770]">Draft</span>
				<span class="border border-[#E2E0DB] bg-white px-2.5 py-0.5 text-xs font-medium text-[#1A1A1A]">private</span>
			</div>
		</div>
	</section>

	<!-- ─── Stat Cards ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Stat Cards — Accent Alternatives</h2>
		<p class="text-sm text-[#7A7770]">Exploring alternatives to the left-border color stripe.</p>

		<!-- Option A: Colored dot + colored label (current) -->
		<div>
			<p class="mb-2 text-xs font-medium uppercase tracking-wider text-[#7A7770]">A — Colored dot + label (current)</p>
			<div class="grid grid-cols-4 gap-4">
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#0055BF]"><span class="inline-block h-2.5 w-2.5 bg-[#0055BF]"></span>In Review</p>
					<p class="font-mono text-2xl font-bold">9</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#00852B]"><span class="inline-block h-2.5 w-2.5 bg-[#00852B]"></span>Accepted</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#D01012]"><span class="inline-block h-2.5 w-2.5 bg-[#D01012]"></span>Rejected</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#B8960C]"><span class="inline-block h-2.5 w-2.5 bg-[#FFD500]"></span>Conflict</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
			</div>
		</div>

		<!-- Option B: Top border -->
		<div>
			<p class="mb-2 text-xs font-medium uppercase tracking-wider text-[#7A7770]">B — Top border</p>
			<div class="grid grid-cols-4 gap-4">
				<div class="border border-[#E2E0DB] border-t-2 border-t-[#0055BF] bg-white p-4">
					<p class="text-xs text-[#7A7770]">In Review</p>
					<p class="font-mono text-2xl font-bold">9</p>
				</div>
				<div class="border border-[#E2E0DB] border-t-2 border-t-[#00852B] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Accepted</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] border-t-2 border-t-[#D01012] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Rejected</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] border-t-2 border-t-[#FFD500] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Conflict</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
			</div>
		</div>

		<!-- Option C: Colored number -->
		<div>
			<p class="mb-2 text-xs font-medium uppercase tracking-wider text-[#7A7770]">C — Colored value (no decorative border)</p>
			<div class="grid grid-cols-4 gap-4">
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="text-xs text-[#7A7770]">In Review</p>
					<p class="font-mono text-2xl font-bold text-[#0055BF]">9</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Accepted</p>
					<p class="font-mono text-2xl font-bold text-[#00852B]">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Rejected</p>
					<p class="font-mono text-2xl font-bold text-[#D01012]">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Conflict</p>
					<p class="font-mono text-2xl font-bold text-[#B8960C]">0</p>
				</div>
			</div>
		</div>

		<!-- Option D: Dot indicator -->
		<div>
			<p class="mb-2 text-xs font-medium uppercase tracking-wider text-[#7A7770]">D — Dot indicator next to label</p>
			<div class="grid grid-cols-4 gap-4">
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-1.5 text-xs text-[#7A7770]"><span class="inline-block h-2 w-2 bg-[#0055BF]"></span>In Review</p>
					<p class="font-mono text-2xl font-bold">9</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-1.5 text-xs text-[#7A7770]"><span class="inline-block h-2 w-2 bg-[#00852B]"></span>Accepted</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-1.5 text-xs text-[#7A7770]"><span class="inline-block h-2 w-2 bg-[#D01012]"></span>Rejected</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-1.5 text-xs text-[#7A7770]"><span class="inline-block h-2 w-2 bg-[#FFD500]"></span>Conflict</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
			</div>
		</div>

		<!-- Option E: Bottom bar -->
		<div>
			<p class="mb-2 text-xs font-medium uppercase tracking-wider text-[#7A7770]">E — Bottom bar</p>
			<div class="grid grid-cols-4 gap-4">
				<div class="border border-[#E2E0DB] border-b-2 border-b-[#0055BF] bg-white p-4">
					<p class="text-xs text-[#7A7770]">In Review</p>
					<p class="font-mono text-2xl font-bold">9</p>
				</div>
				<div class="border border-[#E2E0DB] border-b-2 border-b-[#00852B] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Accepted</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] border-b-2 border-b-[#D01012] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Rejected</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] border-b-2 border-b-[#FFD500] bg-white p-4">
					<p class="text-xs text-[#7A7770]">Conflict</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
			</div>
		</div>

		<!-- Option F: Colored label + dot (combined) -->
		<div>
			<p class="mb-2 text-xs font-medium uppercase tracking-wider text-[#7A7770]">F — Colored label + dot (combined, bigger dot)</p>
			<div class="grid grid-cols-4 gap-4">
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#0055BF]"><span class="inline-block h-2.5 w-2.5 bg-[#0055BF]"></span>In Review</p>
					<p class="font-mono text-2xl font-bold">9</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#00852B]"><span class="inline-block h-2.5 w-2.5 bg-[#00852B]"></span>Accepted</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#D01012]"><span class="inline-block h-2.5 w-2.5 bg-[#D01012]"></span>Rejected</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
				<div class="border border-[#E2E0DB] bg-white p-4">
					<p class="flex items-center gap-2 text-xs font-medium text-[#B8960C]"><span class="inline-block h-2.5 w-2.5 bg-[#FFD500]"></span>Conflict</p>
					<p class="font-mono text-2xl font-bold">0</p>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Profile Cards ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Profile Cards</h2>
		<div class="grid grid-cols-3 gap-4">
			<a href="#" class="border border-[#E2E0DB] bg-white p-4 transition-colors hover:border-[#7A7770]">
				<p class="font-semibold">My Star Wars Collection</p>
				<p class="text-xs text-[#7A7770]">Set-based profile</p>
				<p class="mt-2 font-mono text-xs text-[#7A7770]">v3 | 617 parts</p>
			</a>
			<a href="#" class="border border-[#E2E0DB] bg-white p-4 transition-colors hover:border-[#7A7770]">
				<p class="font-semibold">Presort</p>
				<p class="text-xs text-[#7A7770]">Rule-based profile</p>
				<p class="mt-2 font-mono text-xs text-[#7A7770]">v3 | 0 parts</p>
			</a>
			<a href="#" class="border border-[#E2E0DB] bg-white p-4 transition-colors hover:border-[#7A7770]">
				<p class="font-semibold">Basics</p>
				<p class="text-xs text-[#7A7770]">by color and type</p>
				<p class="mt-2 font-mono text-xs text-[#7A7770]">v1 | 0 parts</p>
			</a>
		</div>
	</section>

	<!-- ─── Alert / Message Banners ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Alerts & Messages</h2>
		<div class="space-y-3">
			<div class="border border-[#D01012]/30 bg-[#FEF2F2] p-3 text-sm text-[#9B1D20]">Error: Failed to create profile. Please check your input.</div>
			<div class="border border-[#00852B]/30 bg-emerald-50 p-3 text-sm text-[#00852B]">Success: Profile published and ready for deployment.</div>
			<div class="border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">Warning: AI assistant requires an OpenRouter API key.</div>
			<div class="border border-[#0055BF]/30 bg-sky-50 p-3 text-sm text-[#0055BF]">Info: This profile has been forked 3 times.</div>
		</div>
	</section>

	<!-- ─── Version History ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Version History</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="space-y-3">
				<div class="border border-[#E2E0DB] p-4">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							<span class="font-mono text-sm font-bold">v3</span>
							<span class="border border-[#00852B]/30 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-[#00852B]">Published</span>
						</div>
						<div class="text-right font-mono text-xs text-[#7A7770]">
							<p>617 parts</p>
							<p>100.0% coverage</p>
						</div>
					</div>
					<p class="mt-1 text-sm">Updated set configuration</p>
					<p class="mt-0.5 text-xs text-[#7A7770]">just now</p>
				</div>
				<div class="border border-[#E2E0DB] p-4">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							<span class="font-mono text-sm font-bold">v2</span>
							<span class="border border-[#00852B]/30 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-[#00852B]">Published</span>
						</div>
						<div class="text-right font-mono text-xs text-[#7A7770]">
							<p>366 parts</p>
							<p>100.0% coverage</p>
						</div>
					</div>
					<p class="mt-1 text-sm">Initial set configuration</p>
					<p class="mt-0.5 text-xs text-[#7A7770]">4h ago</p>
				</div>
				<div class="border border-[#E2E0DB] p-4">
					<div class="flex items-center justify-between">
						<span class="font-mono text-sm font-bold">v1</span>
						<div class="text-right font-mono text-xs text-[#7A7770]">
							<p>0 parts</p>
							<p>n/a coverage</p>
						</div>
					</div>
					<p class="mt-1 text-sm">Initial version</p>
					<p class="mt-0.5 text-xs text-[#7A7770]">4h ago</p>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Navigation Tab Styles ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Tab Navigation</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="inline-flex border border-[#E2E0DB] p-1">
				<button class="px-3 py-1.5 text-sm font-medium text-[#7A7770] hover:text-[#1A1A1A] hover:bg-[#F7F6F3]">Discover</button>
				<button class="px-3 py-1.5 text-sm font-medium text-[#7A7770] hover:text-[#1A1A1A] hover:bg-[#F7F6F3]">My Library</button>
				<button class="bg-[#FEF2F2] px-3 py-1.5 text-sm font-medium text-[#D01012]">My Profiles</button>
			</div>
		</div>
	</section>

	<!-- ─── Spacing Reference ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Spacing Scale</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="space-y-2">
				{#each [1, 2, 3, 4, 6, 8, 12, 16] as size}
					<div class="flex items-center gap-4">
						<span class="w-12 font-mono text-xs text-[#7A7770]">{size * 4}px</span>
						<div class="h-3 bg-[#D01012]/20" style="width: {size * 4}px"></div>
						<span class="font-mono text-xs text-[#7A7770]">p-{size}</span>
					</div>
				{/each}
			</div>
		</div>
	</section>
</div>

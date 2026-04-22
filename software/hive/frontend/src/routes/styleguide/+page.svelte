<script lang="ts">
	import { Button, Alert, Tooltip } from '$lib/components/primitives';
</script>

<svelte:head>
	<title>Style Guide - Hive</title>
</svelte:head>

<div class="space-y-16 pb-20">
	<!-- Header -->
	<div>
		<h1 class="text-3xl font-bold tracking-tight">Style Guide</h1>
		<p class="mt-1 text-sm text-[#7A7770]">Hive Design System — "Precision Play"</p>
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
				<span class="border border-[#00852B]/30 bg-[#00852B]/10 px-2.5 py-0.5 text-xs font-medium text-[#00852B]">Published</span>
				<span class="border border-[#0055BF]/30 bg-[#0055BF]/8 px-2.5 py-0.5 text-xs font-medium text-[#0055BF]">In Review</span>
				<span class="border border-[#FFD500]/30 bg-[#FFD500]/15 px-2.5 py-0.5 text-xs font-medium text-[#A16207]">Warning</span>
				<span class="border border-[#D01012]/30 bg-[#D01012]/8 px-2.5 py-0.5 text-xs font-medium text-[#D01012]">Rejected</span>
				<span class="border border-[#E2E0DB] bg-[#F7F6F3] px-2.5 py-0.5 text-xs font-medium text-[#7A7770]">Draft</span>
				<span class="border border-[#E2E0DB] bg-white px-2.5 py-0.5 text-xs font-medium text-[#1A1A1A]">private</span>
			</div>
		</div>
	</section>

	<!-- ─── Stat Cards ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Stat Cards</h2>
		<p class="text-sm text-[#7A7770]">Colored label + dot indicator. The label text and dot carry the semantic color.</p>
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
		<p class="text-xs text-[#7A7770]">Pattern: 2.5x2.5 color dot + colored label text (font-medium) · Mono 2xl bold value · White card with standard border</p>
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
			<div class="bg-[#D01012]/8 p-3 text-sm text-[#D01012]">Error: Failed to create profile. Please check your input.</div>
			<div class="bg-[#00852B]/10 p-3 text-sm text-[#00852B]">Success: Profile published and ready for deployment.</div>
			<div class="bg-[#FFD500]/15 p-3 text-sm text-[#A16207]">Warning: AI assistant requires an OpenRouter API key.</div>
			<div class="bg-[#0055BF]/8 p-3 text-sm text-[#0055BF]">Info: This profile has been forked 3 times.</div>
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
							<span class="border border-[#00852B]/30 bg-[#00852B]/10 px-2 py-0.5 text-xs font-medium text-[#00852B]">Published</span>
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
							<span class="border border-[#00852B]/30 bg-[#00852B]/10 px-2 py-0.5 text-xs font-medium text-[#00852B]">Published</span>
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

	<!-- ─── Modal / Dialog ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Modal / Dialog</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="relative overflow-hidden border border-black/10 bg-black/50 p-8" style="min-height: 260px">
				<div class="mx-auto w-full max-w-lg bg-white p-6">
					<div class="mb-4 flex items-center justify-between">
						<h3 class="text-lg font-semibold text-[#1A1A1A]">Confirm Action</h3>
						<button class="p-1 text-[#7A7770] hover:text-[#7A7770]">
							<svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
								<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
							</svg>
						</button>
					</div>
					<p class="mb-6 text-sm text-[#7A7770]">Are you sure you want to delete this machine? This action cannot be undone.</p>
					<div class="flex justify-end gap-3">
						<button class="border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Cancel</button>
						<button class="bg-[#9B1D20] px-4 py-2 text-sm font-medium text-white hover:bg-[#7A1517]">Delete</button>
					</div>
				</div>
			</div>
			<p class="mt-2 text-xs text-[#7A7770]">Backdrop: bg-black/50 · Content: max-w-lg bg-white p-6 · Dismissible via ESC and backdrop click</p>
		</div>
	</section>

	<!-- ─── Dropdown Menu ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Dropdown Menu</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="flex gap-8">
				<div class="relative">
					<button class="flex items-center gap-2 border border-[#E2E0DB] px-3 py-1.5 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">
						User Menu
						<svg class="h-4 w-4 text-[#7A7770]" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<div class="absolute left-0 z-50 mt-1 w-56 border border-[#E2E0DB] bg-white py-1">
						<div class="px-4 py-2 text-xs font-medium uppercase tracking-wider text-[#7A7770]">Account</div>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-[#1A1A1A] hover:bg-[#F7F6F3]">Settings</a>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-[#1A1A1A] hover:bg-[#F7F6F3]">Profile</a>
						<div class="my-1 border-b border-[#E2E0DB]"></div>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-[#9B1D20] hover:bg-[#FEF2F2]">Sign out</a>
					</div>
				</div>
				<div class="relative">
					<button class="border border-[#E2E0DB] p-1.5 text-[#7A7770] hover:bg-[#F7F6F3]">
						<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
							<path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
						</svg>
					</button>
					<div class="absolute left-0 z-50 mt-1 w-48 border border-[#E2E0DB] bg-white py-1">
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-[#1A1A1A] hover:bg-[#F7F6F3]">Edit</a>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-[#1A1A1A] hover:bg-[#F7F6F3]">Duplicate</a>
						<div class="my-1 border-b border-[#E2E0DB]"></div>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-[#9B1D20] hover:bg-[#FEF2F2]">Delete</a>
					</div>
				</div>
			</div>
			<p class="mt-4 text-xs text-[#7A7770]">Three-dot menu for contextual actions · User menu with section dividers</p>
		</div>
	</section>

	<!-- ─── Icon Buttons ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Icon Buttons</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="flex flex-wrap items-center gap-4">
				<div class="flex items-center gap-1">
					<button class="p-1 text-[#7A7770] hover:text-[#1A1A1A]" title="Move up">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button class="p-1 text-[#7A7770] hover:text-[#1A1A1A]" title="Move down">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button class="p-1 text-[#7A7770] hover:text-[#D01012]" title="Delete">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
						</svg>
					</button>
				</div>
				<span class="text-xs text-[#7A7770]">Reorder + Delete</span>
				<div class="mx-2 h-6 border-l border-[#E2E0DB]"></div>
				<button class="p-1 text-[#7A7770] hover:text-[#1A1A1A]" title="Close">
					<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
					</svg>
				</button>
				<span class="text-xs text-[#7A7770]">Close</span>
				<div class="mx-2 h-6 border-l border-[#E2E0DB]"></div>
				<button class="border border-[#E2E0DB] p-1.5 text-[#7A7770] hover:bg-[#F7F6F3]" title="More">
					<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
						<path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
					</svg>
				</button>
				<span class="text-xs text-[#7A7770]">Three-dot menu</span>
			</div>
			<p class="mt-3 text-xs text-[#7A7770]">Ghost: p-1 text-[#7A7770] hover:text-[#1A1A1A] · Destructive hover: hover:text-[#D01012] · Bordered: border + p-1.5</p>
		</div>
	</section>

	<!-- ─── Accordion / Collapsible ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Accordion / Collapsible</h2>
		<div class="border border-[#E2E0DB] bg-white">
			<div class="cursor-pointer border-b border-[#E2E0DB] px-3 py-2 hover:bg-[#F7F6F3] bg-[#D01012]/8">
				<div class="flex items-center gap-2">
					<svg class="h-3.5 w-3.5 shrink-0 text-[#7A7770] rotate-90 transition-transform" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
					</svg>
					<span class="text-sm font-medium text-[#1A1A1A]">Expanded Item</span>
					<span class="ml-auto bg-[#F7F6F3] px-1.5 py-0.5 text-xs font-medium text-[#7A7770]">128</span>
				</div>
			</div>
			<div class="border-b border-[#E2E0DB] bg-white px-3 py-3">
				<p class="text-sm text-[#7A7770]">Expanded content area — form fields, details, actions go here.</p>
			</div>
			<div class="cursor-pointer border-b border-[#E2E0DB] px-3 py-2 hover:bg-[#F7F6F3]">
				<div class="flex items-center gap-2">
					<svg class="h-3.5 w-3.5 shrink-0 text-[#7A7770] transition-transform" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
					</svg>
					<span class="text-sm font-medium text-[#1A1A1A]">Collapsed Item</span>
					<span class="ml-auto bg-[#F7F6F3] px-1.5 py-0.5 text-xs font-medium text-[#7A7770]">64</span>
				</div>
				<div class="ml-5.5 mt-0.5 truncate text-xs text-[#7A7770]">Summary preview text when collapsed</div>
			</div>
			<div class="cursor-pointer border-b border-[#E2E0DB] px-3 py-2 hover:bg-[#F7F6F3] opacity-50">
				<div class="flex items-center gap-2">
					<svg class="h-3.5 w-3.5 shrink-0 text-[#7A7770] transition-transform" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
					</svg>
					<span class="text-sm font-medium text-[#7A7770] line-through">Disabled Item</span>
					<span class="shrink-0 text-[10px] uppercase tracking-wide text-[#7A7770]">off</span>
				</div>
			</div>
		</div>
		<p class="text-xs text-[#7A7770]">Active row: bg-[#D01012]/8 · Chevron rotates 90deg when open · Disabled: opacity-50 + line-through</p>
	</section>

	<!-- ─── Set Rule Card ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Set Rule Card</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<p class="mb-3 text-xs font-medium uppercase tracking-wider text-[#7A7770]">Collapsed (in rule list)</p>
			<div class="mb-6 flex cursor-pointer items-center gap-2 border-b border-[#E2E0DB] px-3 py-2 hover:bg-[#F7F6F3]">
				<img src="https://cdn.rebrickable.com/media/sets/21242-1/120155.jpg" alt="The End Arena" class="h-16 w-16 shrink-0 object-contain" />
				<div class="min-w-0 flex-1">
					<span class="text-sm font-medium text-[#1A1A1A]">The End Arena</span>
					<div class="mt-0.5 text-xs text-[#7A7770]">21242-1 · 2023 · 252 parts</div>
				</div>
				<span class="bg-[#F7F6F3] px-1.5 py-0.5 text-xs font-medium text-[#7A7770]">252</span>
			</div>
			<p class="mb-3 text-xs font-medium uppercase tracking-wider text-[#7A7770]">Expanded (editor view)</p>
			<div class="border border-[#E2E0DB] bg-white px-3 py-3">
				<div class="mb-3 flex gap-4">
					<img src="https://cdn.rebrickable.com/media/sets/21242-1/120155.jpg" alt="The End Arena" class="h-32 w-32 shrink-0 object-contain" />
					<div class="min-w-0 flex-1">
						<input type="text" value="The End Arena" class="mb-1 w-full border border-[#E2E0DB] px-2 py-1 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
						<div class="mb-2 text-xs text-[#7A7770]">21242-1 · 2023 · 252 parts</div>
						<a href="#" class="inline-flex items-center gap-1 text-xs text-[#D01012] hover:underline">
							View on Rebrickable
							<svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
								<path fill-rule="evenodd" d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm7.25-.75a.75.75 0 01.75-.75h3.5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V6.31l-5.97 5.97a.75.75 0 01-1.06-1.06l5.97-5.97H12.25a.75.75 0 01-.75-.75z" clip-rule="evenodd" />
							</svg>
						</a>
					</div>
				</div>
				<div class="flex items-center gap-4">
					<label class="flex items-center gap-1.5 text-xs text-[#7A7770]">
						<input type="checkbox" class="h-4 w-4 accent-[#D01012]" />
						Include spare parts
					</label>
					<label class="flex items-center gap-1 text-xs text-[#7A7770]">
						<input type="checkbox" class="h-4 w-4 accent-[#D01012]" />
						Disabled
					</label>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Progress Bars ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Progress Bars</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="space-y-4">
				<div>
					<div class="mb-1 flex justify-between text-xs text-[#7A7770]">
						<span>Set Progress</span>
						<span>73%</span>
					</div>
					<div class="h-1.5 w-full bg-[#E2E0DB]">
						<div class="h-full bg-[#00852B] transition-all" style="width: 73%"></div>
					</div>
				</div>
				<div>
					<div class="mb-1 flex justify-between text-xs text-[#7A7770]">
						<span>Category Coverage</span>
						<span>45%</span>
					</div>
					<div class="h-1.5 w-full bg-[#E2E0DB]">
						<div class="h-full bg-[#0055BF] transition-all" style="width: 45%"></div>
					</div>
				</div>
				<div>
					<div class="mb-1 flex justify-between text-xs text-[#7A7770]">
						<span>Warning Zone</span>
						<span>12%</span>
					</div>
					<div class="h-1.5 w-full bg-[#E2E0DB]">
						<div class="h-full bg-[#FFD500] transition-all" style="width: 12%"></div>
					</div>
				</div>
			</div>
			<p class="mt-3 text-xs text-[#7A7770]">Track: h-1.5 bg-[#E2E0DB] · Fill: h-full transition-all · Colors: success/info/warning</p>
		</div>
	</section>

	<!-- ─── Spinner / Loading ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Loading States</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="flex items-center gap-8">
				<div class="flex flex-col items-center gap-2">
					<div class="h-8 w-8 animate-spin border-4 border-[#E2E0DB] border-t-[#D01012]" style="border-radius: 50%"></div>
					<span class="text-xs text-[#7A7770]">Page Spinner</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<div class="h-4 w-4 animate-spin border-2 border-[#E2E0DB] border-t-[#7A7770]" style="border-radius: 50%"></div>
					<span class="text-xs text-[#7A7770]">Inline Spinner</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<div class="py-4 text-center text-xs text-[#7A7770]">Searching...</div>
					<span class="text-xs text-[#7A7770]">Text Loading</span>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Search with Results ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Search with Inline Results</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="max-w-md border border-[#E2E0DB] bg-white p-3">
				<div class="mb-2 flex items-center justify-between">
					<h3 class="text-sm font-semibold text-[#1A1A1A]">Add LEGO Set</h3>
					<button class="p-1 text-[#7A7770] hover:text-[#7A7770]">
						<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
				</div>
				<input type="text" value="Minecraft" readonly class="mb-2 w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
				<div class="mb-2 flex items-center gap-2">
					<input type="number" placeholder="From year" class="w-24 border border-[#E2E0DB] px-2 py-1 text-xs focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
					<span class="text-xs text-[#7A7770]">&ndash;</span>
					<input type="number" placeholder="To year" class="w-24 border border-[#E2E0DB] px-2 py-1 text-xs focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
				</div>
				<div class="max-h-40 space-y-1 overflow-y-auto">
					<button class="flex w-full items-center gap-3 border border-[#E2E0DB] p-2 text-left hover:bg-[#F7F6F3]">
						<div class="flex h-12 w-12 shrink-0 items-center justify-center bg-[#F7F6F3] text-xs text-[#7A7770]">IMG</div>
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium text-[#1A1A1A]">The Panda Haven</div>
							<div class="text-xs text-[#7A7770]">21245-1 · 2023 · 553 parts</div>
						</div>
					</button>
					<button class="flex w-full items-center gap-3 border border-[#E2E0DB] p-2 text-left hover:bg-[#F7F6F3]">
						<div class="flex h-12 w-12 shrink-0 items-center justify-center bg-[#F7F6F3] text-xs text-[#7A7770]">IMG</div>
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium text-[#1A1A1A]">The End Arena</div>
							<div class="text-xs text-[#7A7770]">21242-1 · 2023 · 252 parts</div>
						</div>
					</button>
				</div>
			</div>
			<p class="mt-2 text-xs text-[#7A7770]">Debounced input · Scrollable result list (max-h-64) · Thumbnail 12x12 + metadata · Year filter fields</p>
		</div>
	</section>

	<!-- ─── Data Table ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Data Table</h2>
		<div class="border border-[#E2E0DB] bg-white">
			<table class="min-w-full divide-y divide-[#E2E0DB]">
				<thead class="bg-[#F7F6F3]">
					<tr>
						<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-[#7A7770]">Name</th>
						<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-[#7A7770]">Role</th>
						<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-[#7A7770]">Status</th>
						<th class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-[#7A7770]">Actions</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-[#E2E0DB]">
					<tr class="hover:bg-[#F7F6F3]">
						<td class="whitespace-nowrap px-6 py-4 text-sm font-medium text-[#1A1A1A]">Marc Neuhaus</td>
						<td class="whitespace-nowrap px-6 py-4 text-sm text-[#7A7770]">Admin</td>
						<td class="whitespace-nowrap px-6 py-4"><span class="border border-[#00852B]/30 bg-[#00852B]/10 px-2.5 py-0.5 text-xs font-medium text-[#00852B]">Active</span></td>
						<td class="whitespace-nowrap px-6 py-4 text-right text-sm text-[#D01012]">Edit</td>
					</tr>
					<tr class="opacity-50 hover:bg-[#F7F6F3]">
						<td class="whitespace-nowrap px-6 py-4 text-sm font-medium text-[#1A1A1A]">Guest User</td>
						<td class="whitespace-nowrap px-6 py-4 text-sm text-[#7A7770]">Member</td>
						<td class="whitespace-nowrap px-6 py-4"><span class="border border-[#E2E0DB] bg-[#F7F6F3] px-2.5 py-0.5 text-xs font-medium text-[#7A7770]">Inactive</span></td>
						<td class="whitespace-nowrap px-6 py-4 text-right text-sm text-[#D01012]">Edit</td>
					</tr>
				</tbody>
			</table>
		</div>
		<p class="text-xs text-[#7A7770]">Header: bg-[#F7F6F3] uppercase · Rows: divide-y hover:bg-[#F7F6F3] · Inactive: opacity-50</p>
	</section>

	<!-- ─── Pagination ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Pagination</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="flex items-center gap-1">
				<button class="border border-[#E2E0DB] px-3 py-1.5 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3] disabled:opacity-50" disabled>Previous</button>
				<button class="border border-[#E2E0DB] px-3 py-1.5 text-sm font-medium bg-[#D01012] text-white">1</button>
				<button class="border border-[#E2E0DB] px-3 py-1.5 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">2</button>
				<button class="border border-[#E2E0DB] px-3 py-1.5 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">3</button>
				<span class="px-1 text-[#7A7770]">...</span>
				<button class="border border-[#E2E0DB] px-3 py-1.5 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">12</button>
				<button class="border border-[#E2E0DB] px-3 py-1.5 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Next</button>
			</div>
			<p class="mt-3 text-xs text-[#7A7770]">Active page: bg-[#D01012] text-white · Disabled: disabled:opacity-50 · Ellipsis for large page counts</p>
		</div>
	</section>

	<!-- ─── Empty States ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Empty States</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="grid gap-4 sm:grid-cols-2">
				<div class="border border-[#E2E0DB] p-8 text-center">
					<p class="text-sm text-[#7A7770]">No machines yet. Add one to get started.</p>
					<button class="mt-3 bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]">Add Machine</button>
				</div>
				<div class="border border-[#E2E0DB] p-8 text-center">
					<p class="text-sm text-[#7A7770]">No results found for your search.</p>
					<button class="mt-3 border border-[#E2E0DB] bg-white px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Clear Filters</button>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── AI Chat Messages ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">AI Chat Messages</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="space-y-3">
				<!-- User message -->
				<div class="ml-8">
					<div class="mb-1 text-right text-xs font-medium text-[#D01012]">You</div>
					<div class="border border-[#D01012]/20 bg-[#FEF2F2] p-3 text-sm text-[#1A1A1A]">
						Add all Minecraft sets from 2023
					</div>
				</div>
				<!-- AI message with tool trace -->
				<div class="mr-8">
					<div class="mb-1 text-xs font-medium text-[#00852B]">AI</div>
					<div class="space-y-1.5">
						<!-- Tool trace -->
						<div class="border border-[#00852B]/15 bg-[#00852B]/5 px-3 py-2 text-xs">
							<div class="flex items-center gap-1.5 font-medium text-[#00852B]">
								<svg class="h-3 w-3 shrink-0 text-[#00852B]/60" viewBox="0 0 20 20" fill="currentColor">
									<path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
								</svg>
								Searched sets for "Minecraft"
							</div>
							<div class="mt-0.5 text-[#00852B]/60">Found 22 sets for "Minecraft": The Panda Haven (21245-1), The End Arena (21242-1), ...</div>
						</div>
						<!-- AI content -->
						<div class="border border-[#00852B]/10 bg-white p-3 text-sm text-[#1A1A1A]">
							I found 22 Minecraft sets from 2023. I'll add them all as set rules.
						</div>
					</div>
				</div>
				<!-- Progress indicator -->
				<div class="mr-8">
					<div class="border border-[#00852B]/15 bg-[#00852B]/5 px-3 py-2 text-xs">
						<div class="flex items-center gap-1.5 text-[#00852B]/60">
							<div class="h-3 w-3 shrink-0 animate-spin border-2 border-[#00852B]/20 border-t-[#00852B]" style="border-radius: 50%"></div>
							Searching sets for "Minecraft"...
						</div>
					</div>
				</div>
			</div>
			<p class="mt-3 text-xs text-[#7A7770]">User: ml-8 bg-[#D01012]/8 border-[#D01012]/20 · AI: mr-8 bg-white border-[#00852B]/10 · Tool trace: bg-[#00852B]/5 border-[#00852B]/15</p>
		</div>
	</section>

	<!-- ─── Popover / Positioned Form ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Popover</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="relative inline-block">
				<button class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]">Save Version</button>
				<div class="absolute left-0 top-full z-50 mt-2 w-72 border border-[#E2E0DB] bg-white p-4">
					<h3 class="mb-2 text-sm font-semibold">Save New Version</h3>
					<input type="text" placeholder="Change note (optional)" class="mb-3 w-full border border-[#E2E0DB] px-2 py-1 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
					<div class="flex justify-end gap-2">
						<button class="border border-[#E2E0DB] bg-white px-3 py-1.5 text-xs font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Cancel</button>
						<button class="bg-[#D01012] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#B00E10]">Save</button>
					</div>
				</div>
			</div>
			<p class="mt-20 text-xs text-[#7A7770]">Absolute positioned · Backdrop dismiss · Small form layout</p>
		</div>
	</section>

	<!-- ─── Unsaved Changes Bar ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Unsaved Changes Bar</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="border-t border-[#E2E0DB] bg-white px-4 py-3">
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-2 text-sm text-[#7A7770]">
						<span class="inline-block h-2 w-2 bg-[#FFD500]"></span>
						Unsaved changes
					</div>
					<div class="flex gap-2">
						<button class="border border-[#E2E0DB] bg-white px-3 py-1.5 text-xs font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Discard</button>
						<button class="bg-[#D01012] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#B00E10]">Save</button>
					</div>
				</div>
			</div>
			<p class="mt-2 text-xs text-[#7A7770]">Fixed to bottom of viewport · Amber indicator dot · Appears only when dirty state</p>
		</div>
	</section>

	<!-- ─── Select Dropdown ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Select Dropdown</h2>
		<div class="border border-[#E2E0DB] bg-white p-6">
			<div class="flex max-w-lg gap-4">
				<div class="flex-1">
					<label class="mb-1 block text-sm font-medium">Machine</label>
					<select class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]">
						<option>All Machines</option>
						<option>Sorter Alpha</option>
						<option>Sorter Beta</option>
					</select>
				</div>
				<div class="flex-1">
					<label class="mb-1 block text-sm font-medium">AI Model</label>
					<select class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]">
						<option>Claude Sonnet 4</option>
						<option>GPT-4o</option>
						<option>Gemini Pro</option>
					</select>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Card Grid ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Card Grid</h2>
		<div class="grid grid-cols-3 gap-4">
			<div class="border border-[#E2E0DB] border-t-2 border-t-[#00852B] bg-white text-left">
				<div class="aspect-square overflow-hidden bg-[#F7F6F3]">
					<div class="flex h-full items-center justify-center text-sm text-[#7A7770]">Image</div>
				</div>
				<div class="p-3">
					<div class="mb-2 flex flex-wrap gap-1">
						<span class="border border-[#00852B]/30 bg-[#00852B]/10 px-2 py-0.5 text-xs font-medium text-[#00852B]">Accepted</span>
					</div>
					<p class="font-mono text-xs text-[#7A7770]">Plate 2x4 · Red</p>
				</div>
			</div>
			<div class="border border-[#E2E0DB] border-t-2 border-t-[#0055BF] bg-white text-left">
				<div class="aspect-square overflow-hidden bg-[#F7F6F3]">
					<div class="flex h-full items-center justify-center text-sm text-[#7A7770]">Image</div>
				</div>
				<div class="p-3">
					<div class="mb-2 flex flex-wrap gap-1">
						<span class="border border-[#0055BF]/30 bg-[#0055BF]/8 px-2 py-0.5 text-xs font-medium text-[#0055BF]">In Review</span>
					</div>
					<p class="font-mono text-xs text-[#7A7770]">Brick 1x2 · Blue</p>
				</div>
			</div>
			<div class="border border-[#E2E0DB] border-t-2 border-t-[#D01012] bg-white text-left">
				<div class="aspect-square overflow-hidden bg-[#F7F6F3]">
					<div class="flex h-full items-center justify-center text-sm text-[#7A7770]">Image</div>
				</div>
				<div class="p-3">
					<div class="mb-2 flex flex-wrap gap-1">
						<span class="border border-[#D01012]/30 bg-[#D01012]/8 px-2 py-0.5 text-xs font-medium text-[#D01012]">Rejected</span>
					</div>
					<p class="font-mono text-xs text-[#7A7770]">Tile 1x1 · White</p>
				</div>
			</div>
		</div>
		<p class="text-xs text-[#7A7770]">Top border color encodes status · Square image area · Badge + metadata below</p>
	</section>

	<!-- ─── Primitives: Button ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Primitives · Button</h2>
		<div class="space-y-6 border border-border bg-surface p-6">
			<div>
				<p class="mb-2 text-xs uppercase tracking-wider text-text-muted">Variants (md)</p>
				<div class="flex flex-wrap gap-3">
					<Button variant="primary">Primary</Button>
					<Button variant="secondary">Secondary</Button>
					<Button variant="danger">Danger</Button>
					<Button variant="ghost">Ghost</Button>
				</div>
			</div>
			<div>
				<p class="mb-2 text-xs uppercase tracking-wider text-text-muted">Sizes</p>
				<div class="flex flex-wrap items-center gap-3">
					<Button size="sm">Small</Button>
					<Button size="md">Medium</Button>
				</div>
			</div>
			<div>
				<p class="mb-2 text-xs uppercase tracking-wider text-text-muted">States</p>
				<div class="flex flex-wrap gap-3">
					<Button disabled>Disabled</Button>
					<Button loading>Loading</Button>
					<Button variant="secondary" disabled>Secondary disabled</Button>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Primitives: Alert ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Primitives · Alert</h2>
		<div class="space-y-3 border border-border bg-surface p-6">
			<Alert variant="success" title="Upload complete">
				42 samples synced from the Sorter.
			</Alert>
			<Alert variant="warning" title="Calibration drift detected">
				Recalibrate the classification chamber before the next capture run.
			</Alert>
			<Alert variant="danger" title="Model import failed">
				The uploaded artifact is missing a tokenizer config.
			</Alert>
			<Alert variant="info">
				Review decisions auto-save as you go.
			</Alert>
		</div>
	</section>

	<!-- ─── Primitives: Tooltip ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Primitives · Tooltip</h2>
		<div class="flex flex-wrap gap-8 border border-border bg-surface p-10">
			<Tooltip text="Appears above">
				<Button variant="secondary" size="sm">Hover top</Button>
			</Tooltip>
			<Tooltip text="Appears below" placement="bottom">
				<Button variant="secondary" size="sm">Hover bottom</Button>
			</Tooltip>
			<Tooltip text="Appears right" placement="right">
				<Button variant="secondary" size="sm">Hover right</Button>
			</Tooltip>
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

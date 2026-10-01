<script lang="ts">
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import ConditionList from '$lib/components/ConditionList.svelte';
	import ProfileBin from '$lib/components/ProfileBin.svelte';
	import { parts, colors, conditions, bins, warnings, order } from '$lib/site/profile-samples';

	let quantity = $state('6');
	let color = $state('red');
	let current = $state<string>('kit');
</script>

<svelte:head><title>Profiles · Sorter design system</title></svelte:head>

<PageHeader
	title="Profiles"
	lead="How a sorting profile is shown: every part laid out the same way, every rule as a phrase a person can read, every bin as a card or a row. None of it is a field name, a list of IDs or a UUID."
	doc="components"
/>

<SiteSection
	title="Parts"
	lead="One part, laid out the same wherever it appears: the picture, the name, the BrickLink ID in tabular figures, the Rebrickable number only when it is a different one, then the color and the count. The picture is shown whole on whatever it sits on: no dark backdrop, no bars."
>
	<Specimen
		pad={false}
		code={`<PartTile name="Brick 2 x 4" bricklinkId="3001" imgUrl={url}
	color={{ name: 'Red', rgb: 'C91A09' }} quantity={6} found={3} />`}
	>
		<ul class="divide-y divide-line">
			<li>
				<PartTile
					name={parts.brick2x4.name}
					imgUrl={parts.brick2x4.img_url}
					bricklinkId="3001"
					partNum="3001"
				/>
			</li>
			<li>
				<PartTile
					name={parts.brick1x4.name}
					imgUrl={parts.brick1x4.img_url}
					bricklinkId="3010"
					partNum="3010a"
				/>
			</li>
			<li>
				<PartTile
					name={parts.plate2x4.name}
					imgUrl={parts.plate2x4.img_url}
					bricklinkId="3020"
					color={colors.darkBluishGray}
					quantity={4}
				/>
			</li>
			<li>
				<PartTile
					name={parts.brick2x2.name}
					imgUrl={parts.brick2x2.img_url}
					bricklinkId="3003"
					color={colors.yellow}
					quantity={10}
					found={4}
				/>
			</li>
			<li>
				<PartTile
					name={parts.brick1x1.name}
					imgUrl={parts.brick1x1.img_url}
					bricklinkId="3005"
					color={colors.transClear}
					quantity={12}
					found={12}
				/>
			</li>
			<li>
				<PartTile
					name={parts.noPicture.name}
					bricklinkId="3794b"
					color={colors.white}
					quantity={2}
					found={0}
				/>
			</li>
		</ul>
	</Specimen>
	<p class="max-w-2xl text-sm text-ink-muted">
		A row is a line of a list and owns its side padding, like any row in a flush panel. A count
		alone is "×4"; with how many were found it is a kit's progress, and turns green when it is
		complete. A part with no picture, or one that fails to load, shows a quiet blank square, never a
		broken-image icon.
	</p>

	<Specimen
		code={`<PartTile layout="tile" name={part.name} imgUrl={part.img_url}
	bricklinkId={part.part_num} partNum={part.rb_part_num} />`}
	>
		<div class="grid grid-cols-3 gap-x-3 gap-y-5 sm:grid-cols-4 md:grid-cols-6">
			{#each [parts.brick2x4, parts.brick1x4, parts.tile1x2, parts.pin, parts.jumper, parts.noPicture] as part (part.part_num)}
				<PartTile
					layout="tile"
					name={part.name}
					imgUrl={part.img_url}
					bricklinkId={part.part_num}
					partNum={part.rb_part_num}
				/>
			{/each}
		</div>
	</Specimen>
	<p class="max-w-2xl text-sm text-ink-muted">
		A tile is a square picture over its name, for a grid of parts. The picture's box is the same
		size in every tile, and the name takes two lines whatever its length, so the ID under it is in
		the same place in every tile; a longer name is cut, with its full text as the tooltip.
	</p>

	<div class="w-full max-w-[24.375rem]">
		<Panel flush>
			<PartTile
				name={parts.brick2x4.name}
				imgUrl={parts.brick2x4.img_url}
				bricklinkId="3001"
				quantity={Number(quantity) || 0}
			>
				<Select
					label="Color"
					size="sm"
					class="w-40"
					bind:value={color}
					options={[
						{ value: 'red', label: 'Red' },
						{ value: 'blue', label: 'Blue' }
					]}
				/>
				<Input type="number" size="sm" aria-label="Quantity" class="w-20" bind:value={quantity} />
				<Button variant="ghost" size="sm" icon={Trash2} label="Remove" />
			</PartTile>
		</Panel>
	</div>
	<p class="max-w-2xl text-sm text-ink-muted">
		Controls go at the end of a row, such as a color and a quantity on a kit's line. When the row is
		narrower than 40rem they drop under the text, in line with it; here it is at a phone's 390px.
	</p>
</SiteSection>

<SiteSection
	title="Conditions"
	lead="A rule's conditions as phrases, each built the same way: the field, the operator in words, then each value as a chip. A color is its swatch and name, a part its picture, name and ID, a category its name, a number its unit."
>
	<Specimen code={`<ConditionList conditions={bin.conditions} limit={6} />`}>
		<div class="flex flex-col gap-6">
			<ConditionList conditions={conditions.category} />
			<ConditionList conditions={conditions.reds} limit={4} />
			<ConditionList conditions={conditions.onePart} />
			<ConditionList conditions={conditions.parts} />
		</div>
	</Specimen>
	<p class="max-w-2xl text-sm text-ink-muted">
		A condition with many values shows the first few and "+N more", which opens the rest in place. A
		rule for one part, such as BrickLink ID 3001, is one phrase with one chip.
	</p>
	<Specimen>
		<div class="flex flex-col gap-6">
			<ConditionList conditions={conditions.anyOf} />
			<ConditionList conditions={conditions.nested} />
			<ConditionList conditions={conditions.incomplete} />
		</div>
	</Specimen>
	<p class="max-w-2xl text-sm text-ink-muted">
		Conditions joined by "all of" or "any of" say so once above them, and a group inside a rule is
		indented under its own. A condition that cannot be evaluated yet is in the warning tone.
	</p>
</SiteSection>

<SiteSection
	title="Bins"
	lead="One bin as a card: its picture, its place in the order, its name, what kind of bin it is, how many parts it takes and in how many colors, its conditions, and up to six example parts."
>
	<Specimen
		on="canvas"
		code={`<ProfileBin {bin} number={3} warnings={warnings} href="/profiles/{id}/bins/{binId}" />`}
	>
		<div class="grid items-start gap-(--gap-panels) md:grid-cols-2">
			<ProfileBin bin={bins.reds} number={3} />
			<ProfileBin
				bin={bins.kit}
				number={2}
				warnings={warnings.kit}
				progress={{ found: 41, needed: 96 }}
			/>
			<ProfileBin bin={bins.onePart} number={1} />
			<ProfileBin bin={bins.transparent} number={4} />
			<ProfileBin bin={bins.shadowed} number={5} warnings={warnings.shadowed} />
			<ProfileBin bin={bins.tiles} number={6} />
			<ProfileBin bin={bins.gray} number={7} />
			<ProfileBin bin={bins.rest} number={8} />
		</div>
	</Specimen>
	<p class="max-w-2xl text-sm text-ink-muted">
		A rule, a kit with its progress, a category, a color and "Everything else" are laid out the
		same, so a profile's bins can be read down the page. A color bin shows its color where the
		others show a picture; a kit shows its own. A rule that only tests colors takes any part in
		them, so it says that rather than how many parts the catalog knows in those colors. A bin with
		something wrong says so in the warning tone at its foot.
	</p>
	<Specimen on="canvas">
		<div class="grid items-start gap-(--gap-panels) md:grid-cols-2">
			<ProfileBin bin={bins.legacy} />
			<ProfileBin bin={bins.gaps} number={2} warnings={warnings.gaps} plane="well" examples={3} />
		</div>
	</Specimen>
	<p class="max-w-2xl text-sm text-ink-muted">
		A bin from a version saved before bins were described has only a name, and shows as a plain,
		name-only bin. A card on a dialog, which is a surface already, takes the well's fill with
		<code class="font-mono text-ink">plane="well"</code>;
		<code class="font-mono text-ink">examples</code>
		sets the most example parts.
	</p>
</SiteSection>

<SiteSection
	title="Bin rows"
	lead="The same bin on one line, for a list of many: its place, the picture or color, the name, how many parts, any warnings, the kind, and a kit's progress."
>
	<Panel flush>
		<ul class="divide-y divide-line">
			{#each order as entry, i (entry.id)}
				<li>
					<ProfileBin
						layout="row"
						bin={entry.bin}
						number={i + 1}
						warnings={entry.warnings}
						progress={entry.progress}
						selected={current === entry.id}
						onclick={() => (current = entry.id)}
					/>
				</li>
			{/each}
		</ul>
	</Panel>
	<p class="max-w-2xl text-sm text-ink-muted">
		The chosen row takes the primary's tint, like any chosen item. A row is one line, so a profile
		that sorts by color and has hundreds of bins is still a short list to scroll.
	</p>
</SiteSection>

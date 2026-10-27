---
layout: default
title: How to contribute
type: how-to
section: home
slug: contribute
kicker: Contribute
lede: Where the project lives, how to help, when the team meets, and what the assistant in the Discord can do for you.
permalink: /contribute/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-15
---

Sorter V2 is built in the open, by volunteers, and you do not need to be an engineer to help. Reporting a mistake in these pages, or telling the team what happened when you followed one, is a real contribution.

## Ways to help

<ul class="bulleted-list">
  <li><strong>Tell the team what is wrong.</strong> A step that did not work, a part that did not fit, a number that does not match your machine. Post it in the <a href="https://discord.gg/6PZtqkwtaS">Discord</a>, or make a post in one of the issue channels there. A post in an issue channel becomes a GitHub issue, which is the team's to-do list for problems.</li>
  <li><strong>Fix a page yourself.</strong> The <strong>Source</strong> link in the footer of every page opens the docs folder on GitHub. The pages are plain text files inside it, in the same folders as their web addresses, and you can propose a change to one there, as a <em>pull request</em>. If you would rather not use GitHub, ask Balloon to make the change (see Balloon, below).</li>
  <li><strong>Take a bounty.</strong> A bounty is a small, clear task that can be started straight away, posted on the Discord's bounty board with the skills it needs and a time estimate. Claim one only if you can finish it quickly. If you find you cannot, tell the person who posted it early and someone else can take over.</li>
  <li><strong>Work on the machine itself.</strong> Mechanical design (Onshape), electronics (KiCad), software (Python and SvelteKit) and vision (training the part recognition). <a href="{{ '/getting-started/' | relative_url }}#i-want-to-contribute-to-the-project">Getting started</a> says where to begin in each.</li>
</ul>

## Where the project lives

<ul class="bulleted-list">
  <li><strong>GitHub</strong> holds the project's files: these docs, the parts catalog, the firmware and software, and the electronics. GitHub is a website for sharing and reviewing files. The code is at <a href="https://github.com/basicallysource/sorter-v2">github.com/basicallysource/sorter-v2</a>, and the whole organisation is at <a href="https://github.com/basicallysource">github.com/basicallysource</a>.</li>
  <li><strong>Discord</strong> is where the team talks every day, announces meetings and answers questions. <a href="https://discord.gg/6PZtqkwtaS">Join the Discord</a>.</li>
  <li><strong>The CAD</strong> is in Onshape, a free design program that runs in your browser. The documents are public. To be added to the shared folder, ask in the Discord with your Onshape email.</li>
  <li><strong>The parts calculator</strong> lists every part to buy and print, at the layer count you choose: <a href="https://parts-calculator.basically.website/">parts-calculator.basically.website</a>.</li>
  <li><strong>YouTube</strong> has the recorded meetings and progress videos: <a href="https://www.youtube.com/@basicallyhandle">Basically on YouTube</a>.</li>
</ul>

The licence your contribution is shared under is in <a href="https://github.com/basicallysource/sorter-v2/blob/main/CONTRIBUTING.md"><code>CONTRIBUTING.md</code></a>. Read it before you send a change.

## The weekly meeting

There is an engineering meeting every Sunday at 3 pm US Eastern time. Anyone interested can join from the Discord. The welcome message there shows the time in your own time zone.

<ul class="bulleted-list">
  <li><strong>What happens.</strong> The team shares what they built and learned that week, and goes through the problems people have raised. The ones that look critical go on the to-do list, and a volunteer is attached to each.</li>
  <li><strong>If you cannot come.</strong> The meetings are recorded and put on YouTube, and the recordings are shared in the Discord's meeting recordings channel. The <a href="https://www.youtube.com/playlist?list=PLgwKLmohoyyXzct1HrtbVIdbN0LaaNqbu">playlist of past meetings</a> has them all.</li>
  <li><strong>If it is cancelled.</strong> Some weeks the meeting does not happen. That is announced in the Discord.</li>
</ul>

## Balloon, the assistant in the Discord

Balloon is an AI assistant that lives in the Discord. It knows the project's docs, parts catalog, code and history. Ask it a question, or tell it a page is wrong, and it can change the docs and the parts catalog for you. Mention <strong>@Balloon</strong> in a message and say what you want, in your own words. It answers in the same channel.

Each of these channels is set aside for talking to it:

<ul class="bulleted-list">
  <li><strong>#balloon-general</strong> for any question about the project.</li>
  <li><strong>#balloon-electronics</strong> for questions about the electronics: boards, wiring and power.</li>
  <li><strong>#balloon-does-docs</strong> for the docs and the parts catalog: a wrong step, a missing photo, a wrong part count.</li>
</ul>

Balloon does not publish anything by itself. It only proposes a change, and people on the team have to approve it before it goes on the site. It changes the docs, the parts catalog and the wire harness drawings. For firmware, software and CAD it can still answer questions, but a person makes the change. It does not announce dates, prices or unreleased work.

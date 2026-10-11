---
layout: default
title: How to contribute
type: how-to
section: lab
slug: lab-contribute
kicker: Design and research — Contribute
lede: Where the project lives, how to help, when the team meets, and what the assistant in the Discord can do for you.
permalink: /lab/contribute/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-10
---

Sorter V2 is built in the open, by volunteers, and you do not need to be an engineer to help. Reporting a mistake in these pages, or telling the team what happened when you followed one, is a real contribution.

## Where the project lives

<ul class="bulleted-list">
  <li><strong>GitHub</strong> holds the project's files: these docs, the parts catalog, the firmware and software, the electronics and the index of the CAD. GitHub is a website for sharing and reviewing files, and a <em>pull request</em> is how you propose a change to them. The code is at <a href="https://github.com/basicallysource/sorter-v2">github.com/basicallysource/sorter-v2</a>, and the whole organisation is at <a href="https://github.com/basicallysource">github.com/basicallysource</a>.</li>
  <li><strong>Discord</strong> is where the team talks every day, announces meetings and answers questions. <a href="https://discord.gg/6PZtqkwtaS">Join the Discord</a>.</li>
  <li><strong>The CAD</strong> is in Onshape, a free design program that runs in your browser. The documents are public. To be added to the shared folder, ask in the Discord with your Onshape email.</li>
  <li><strong>The parts calculator</strong> lists every part to buy and print, at the layer count you choose: <a href="https://parts-calculator.basically.website/">parts-calculator.basically.website</a>.</li>
  <li><strong>YouTube</strong> has the recorded meetings and progress videos: <a href="https://www.youtube.com/@basicallyhandle">Basically on YouTube</a>.</li>
</ul>

The licence your contribution is shared under is in <a href="https://github.com/basicallysource/sorter-v2/blob/main/CONTRIBUTING.md"><code>CONTRIBUTING.md</code></a>. Read it before you send a change.

## Ways to help

<ul class="bulleted-list">
  <li><strong>Tell the team what is wrong.</strong> A step that did not work, a part that did not fit, a number that does not match your machine. Post it in the Discord, or make a post in one of the issue channels there. A post in an issue channel becomes a GitHub issue, which is the team's to-do list for problems.</li>
  <li><strong>Fix a page yourself.</strong> The <strong>Source</strong> link in the footer of every page opens the docs folder on GitHub. The pages are plain text files inside it, in the same folders as their web addresses, and you can propose a change to one as a pull request.</li>
  <li><strong>Take a bounty.</strong> A bounty is a small, clear task that can be started straight away, posted on the Discord's bounty board with the skills it needs and a time estimate. Claim one only if you can finish it quickly. If you find you cannot, tell the person who posted it early and someone else can take over.</li>
  <li><strong>Work on the machine itself.</strong> Mechanical design (Onshape), electronics (KiCad), software (Python and SvelteKit) and vision (training the part recognition). <a href="{{ '/getting-started/' | relative_url }}#i-want-to-contribute-to-the-project">Getting started</a> says where to begin in each.</li>
</ul>

## The weekly meeting

There is an engineering meeting every Sunday at 3 pm US Eastern time. Anyone interested can join from the Discord. The welcome message there shows the time in your own time zone.

<ul class="bulleted-list">
  <li><strong>What happens.</strong> The team shares what they built and learned that week, and goes through the problems people have raised. The ones that look critical go on the to-do list, and a volunteer is attached to each.</li>
  <li><strong>If you cannot come.</strong> The meetings are recorded and put on YouTube, and the recordings are shared in the Discord's meeting recordings channel. The <a href="https://www.youtube.com/playlist?list=PLgwKLmohoyyXzct1HrtbVIdbN0LaaNqbu">playlist of past meetings</a> has them all.</li>
  <li><strong>If it is cancelled.</strong> Some weeks the meeting does not happen. That is announced in the Discord.</li>
</ul>

## Balloon, the assistant in the Discord

Balloon is an AI assistant that lives in the Discord. It knows the project's docs, parts catalog, code and history, and it can change the docs and the parts catalog for you. To use it, mention <strong>@Balloon</strong> in a message in the server and say what you want, in your own words. It answers in the same channel.

Some examples of what it can do, with real changes it has made:

<ul class="bulleted-list">
  <li><strong>Fix or improve a docs page.</strong> Tell it a page is wrong or unclear and it edits the page and opens a pull request. Examples: <a href="https://github.com/basicallysource/sorter-v2/pull/967">how many holes a beam that fits has</a>, and <a href="https://github.com/basicallysource/sorter-v2/pull/958">how to find a stepper motor's coils by feel</a>, without a multimeter.</li>
  <li><strong>Write a new helper page or draw a diagram.</strong> It draws diagrams and builds pages. Examples: <a href="https://github.com/basicallysource/sorter-v2/pull/902">which socket hole takes the red wire</a> on the 24 V lead, and <a href="https://github.com/basicallysource/sorter-v2/pull/966">a printable sheet of cable labels</a>.</li>
  <li><strong>Correct the parts catalog.</strong> A wrong count, a wrong screw, a part that no longer belongs. Examples: <a href="https://github.com/basicallysource/sorter-v2/pull/927">a bracket counted once too few on the bottom layer</a>, and <a href="https://github.com/basicallysource/sorter-v2/pull/916">retiring parts the machine no longer uses</a>.</li>
  <li><strong>Read a page as a newcomer.</strong> Ask it to read a page as someone who knows LEGO and 3D printing but not electronics, and tell you where that reader would get stuck. It did this for the <a href="https://github.com/basicallysource/sorter-v2/pull/914">bill of materials</a>, and for the design pages in the Lab.</li>
  <li><strong>Answer questions from the project's own record.</strong> It can search the Discord history, the written notes and transcripts of the recorded meetings, the docs and the repositories, and it says so when it cannot find the answer. Ask it to catch you up on a meeting you missed, or to find where something was decided.</li>
  <li><strong>Check the electronics.</strong> It can open the KiCad circuit boards, run the checks for design errors, and export a parts list, the schematic as a PDF, the files a factory needs to make the board, or a picture of it.</li>
  <li><strong>Show you a web page.</strong> It can search the web, and take a screenshot of any public page, including a preview of a docs change before anyone merges it.</li>
  <li><strong>Make a file or a chart.</strong> A spreadsheet of what you asked for, a chart of the numbers, or a poll to ask the channel something.</li>
</ul>

What Balloon will not do:

<ul class="bulleted-list">
  <li><strong>It does not merge anything.</strong> Every pull request it opens is a draft. A person marks it ready for review, and the team then approves it on the Discord's pull request board. A docs change merges when two people approve it.</li>
  <li><strong>It only changes the docs, the parts catalog and the wire harness drawings.</strong> For firmware, software and CAD it can still answer questions and explain, but a person makes the change.</li>
  <li><strong>It does not announce dates, prices or unreleased work.</strong> Those are the team's to say.</li>
  <li><strong>It does not guess.</strong> If it cannot point to where it read something, it says it does not know.</li>
</ul>

The channels with the word <em>balloon</em> in their name are set aside for talking to it.

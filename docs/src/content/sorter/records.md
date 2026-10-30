---
layout: default
title: Records
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-records
kicker: SorterOS — Operate
author: jensr80
lede: The history of everything this machine has sorted, in four views. See totals and trends, name your sorting runs and lots, search and review every piece, and look back at the incidents the machine raised.
permalink: /sorter/records/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the exact look of each
  view has not been checked against a real one.
---

**Records** is the machine's memory. Every piece it sees is saved, and this page lets you read that history back. Opening it changes nothing on the machine. The only things you can change here are your own labels (runs and lots), your answers when you review a piece, and which pieces you export.

Open it from **Records** in the top menu. The menu lists the four views, and the page repeats them as tabs under the heading **Records**:

<ul class="bulleted-list">
  <li><strong>Overview</strong>: totals, trends and a table of each day.</li>
  <li><strong>Runs</strong>: name what you are sorting, and group it into lots.</li>
  <li><strong>Pieces</strong>: every piece, searchable, with a review for each.</li>
  <li><strong>Incidents</strong>: every time the machine stopped to ask for help.</li>
</ul>

Each view has an address of its own: `/records`, `/records/runs`, `/records/pieces` and `/records/incidents`.

<div class="img-placeholder">Screenshot of the Records page on the Overview tab, with the Lifetime panel at the top and the Trends charts below it.</div>

## Overview

**Overview** loads three things one after another, so a panel can appear before the one below it. A figure that has not loaded yet shows a dash.

### Lifetime

The **Lifetime** panel covers every piece seen across all saved runs. Its cells:

<ul class="bulleted-list">
  <li><strong>Pieces seen</strong>, <strong>Distributed</strong> and <strong>Classified</strong>: pieces recorded, pieces that went to a bin, and pieces the machine identified.</li>
  <li><strong>Runs</strong>: the number of separate sessions of the machine software that recorded pieces. It is not the list on the <strong>Runs</strong> tab.</li>
  <li><strong>Hours sorted</strong> and <strong>Hours powered</strong>: time spent sorting, and time the machine was on. Under each is the same time as days, hours and minutes.</li>
  <li><strong>Utilization</strong>: hours sorted as a percentage of hours powered.</li>
  <li><strong>Active days</strong>: days the machine ran.</li>
  <li><strong>Throughput</strong>: average pieces a minute. <strong>Best hour</strong>: the peak pieces a minute in a single hour.</li>
  <li><strong>Unique parts</strong> and <strong>Unique colors</strong>: how many different parts and colors it has seen.</li>
  <li><strong>Total value</strong> and <strong>Value, last 24 hours</strong>: the estimated value of what was sorted, from the BrickLink moving average price. Under each, <em>N of M priced</em> says how many of the pieces had a price. A piece with no price adds nothing to the total.</li>
  <li><strong>First seen</strong> and <strong>Last seen</strong>: the dates of the oldest and newest piece.</li>
</ul>

### Trends

Six charts, loaded a moment after the panel above. If they fail to load the page says **Could not load the chart data.**

<ul class="bulleted-list">
  <li><strong>Pieces per day</strong>: the last year, timed-out pieces left out.</li>
  <li><strong>Throughput per day</strong>: pieces a minute while sorting.</li>
  <li><strong>Unique parts seen</strong>: a running total, all time.</li>
  <li><strong>Classification outcomes</strong>: a ring chart of all pieces by result (<strong>Classified</strong>, <strong>ID failed</strong>, <strong>Unknown</strong>, <strong>Not found</strong>, <strong>Multi drop</strong>, <strong>Timed out</strong>, <strong>Pending</strong>, <strong>Classifying</strong>). Point at a segment for its count and share.</li>
  <li><strong>Top colors</strong> and <strong>Top parts</strong>: the 20 most common, all time. Each bar is drawn in the color of the LEGO color it counts.</li>
</ul>

### Daily activity

A table with one row for each day, newest first, two weeks at a time. The columns are **Day**, **Powered**, **Sorted**, **Pieces** (pieces that went to a bin), **Classified** and **Pieces a minute**. Use **Older two weeks** and **Newer two weeks** under the table to move through it.

**Export CSV** on this panel downloads the daily rows. What the file holds, and the other two exports, are in [Exporting what the machine sorted]({{ '/sorter/export-counts/' | relative_url }}).

## Runs

A **run** is a name you give to a stretch of sorting. A **lot** is the pile of pieces it came from: a box you bought, an order, a collection. Neither one changes how the machine sorts. They label the history, so you can answer "what came out of that box?".

A run lasts across pauses and shutdowns until you start the next one. Each piece belongs to the run that was current when the machine first saw it.

The **Runs and lots** panel has a table of runs, newest first, and under it a table of lots.

<ul class="bulleted-list">
  <li><strong>Run</strong>: its name. The one in progress has a <strong>Current</strong> badge.</li>
  <li><strong>Lot</strong>: the lot it belongs to, or <strong>None</strong>. A badge reads <strong>Adds to the lot</strong> or <strong>Another pass, not counted</strong>.</li>
  <li><strong>From</strong> and <strong>Until</strong>: when it started, and when the next run replaced it (<strong>Now</strong> for the current one).</li>
  <li><strong>Pieces</strong>: how many pieces it holds. Click the number to open the <strong>Pieces</strong> tab filtered to that run.</li>
</ul>

With no runs yet the panel says **No runs yet.**

### Start a run

<ol class="numbered-steps">
  <li>Press <strong>Start a new run</strong>. The form says <em>This ends</em> and the name of the current run: a new run always ends the one before it.</li>
  <li>Type a <strong>Name</strong>.</li>
  <li>Choose the <strong>Lot</strong>: <strong>No lot</strong>, one you made before, or <strong>A new lot…</strong>. For a new lot, type its name in <strong>New lot's name</strong>.</li>
  <li>With a lot chosen, decide <strong>Adds its pieces to the lot</strong>. Leave it on for the first time you put those pieces through. Turn it off for another pass over pieces the lot already counted, such as a finer sort of some of its bins, so the lot still counts each piece once.</li>
  <li>Press <strong>Start the run</strong>.</li>
</ol>

This only starts a new label. It does not start, stop or move the machine. If the machine refuses the form, its reason is shown in red under the fields (for example when the name is empty).

To change a run, press the pencil at the end of its row (labelled **Edit** and the run's name). You can change its name, lot and the **Adds its pieces to the lot** switch, then press **Save**.

### Lots

Each lot row shows:

<ul class="bulleted-list">
  <li><strong>Lot</strong>: its name. Click it to open a window with every part and color in the lot.</li>
  <li><strong>Pieces</strong>: pieces from the runs that add to it. Click the number to open the <strong>Pieces</strong> tab filtered to that lot.</li>
  <li><strong>Runs adding to it</strong> and <strong>Other passes</strong>: how many of its runs add pieces, and how many are repeat passes.</li>
</ul>

The lot window counts each part and color in each of the lot's runs, one column per run. Turn on **Only parts seen more than once** to list only those that came through in more than one run, which is how you see what a second pass picked up again. The list shows 100 rows at a time; press **Show 100 more** (the button gives the count left) to continue.

## Pieces

One row per piece, newest first, 250 to a page. This is where you find a piece, check what the machine decided about it, and tell the machine when it was wrong.

### Find pieces

The bar above the list narrows it. Everything you set is kept in the page address, so Back, a reload, or a link you send someone shows the same list.

<ul class="bulleted-list">
  <li><strong>Search</strong>: type a part number, a part or color name, or the start of a piece id. Several words must all match. It searches a moment after you stop typing.</li>
  <li><strong>Status</strong>: <strong>Any status</strong>, <strong>Classified</strong>, <strong>Unidentified</strong>, <strong>ID failed</strong>, <strong>Multi drop</strong> or <strong>Timed out</strong>.</li>
  <li><strong>Run or lot</strong>: <strong>Any run or lot</strong>, or one run or lot, each with its piece count. Choosing one leaves out timed-out pieces, so the list agrees with the count on the <strong>Runs</strong> tab. Set <strong>Status</strong> to <strong>Timed out</strong> to see them.</li>
  <li><strong>Bin</strong>: <strong>Any bin</strong>, or one bin, written as layer, section and bin with what it takes (for example <code>L0 · S1 · B1 · category</code>).</li>
  <li><strong>From</strong> and <strong>To</strong>: whole days, on your browser's clock.</li>
  <li><strong>Review</strong>: <strong>Any review</strong>, <strong>Reviewed</strong> or <strong>Not reviewed</strong>. A piece counts as reviewed once you have answered any question about it.</li>
  <li><strong>Order</strong>: <strong>Newest first</strong> or <strong>Oldest first</strong>.</li>
  <li><strong>Clear filters</strong> appears once any filter is set.</li>
</ul>

With nothing matching, the list says **No pieces match** and offers **Clear filters**.

The list does not jump while you read it. If more pieces arrive, a line says how many newer pieces arrived since the list started, with a **Show them** button. Pages are moved with the controls above and below the list: first, previous, next and last, or type a page number and press Enter.

**Export CSV** downloads exactly this list, with the same search and filters.

### Read a row

<div class="img-placeholder">Screenshot of two rows in the Pieces list: one classified piece with its pictures and review, and one short row for a piece that was never identified.</div>

<ul class="bulleted-list">
  <li><strong>Pictures</strong>: the camera crops that produced the result, each tagged with the channel it came from (<code>C4</code> is the classification channel). Point at one to enlarge it. <em>+N</em> means N more crops are on the piece's own page. To the right, labelled <strong>Brickognize</strong>, is the catalog picture of the part it was identified as. Pictures load only as a row comes near the screen.</li>
  <li><strong>Name</strong>: the part name and number, with a status badge (<strong>Classified</strong>, <strong>Unidentified</strong>, <strong>ID failed</strong>, <strong>Multi drop</strong>, <strong>Pending</strong>, <strong>Classifying</strong>) and a <strong>Timed out</strong> badge where it applies.</li>
  <li><strong>Color, confidence, value</strong>: the color, how sure the identification was (green at 90% and over, amber from 80%, fading amber from 60%, red below), and the estimated BrickLink value.</li>
  <li><strong>Where</strong>: the bin as <code>L0 · S1 · B1</code>, the time it was seen, and <em>N of M pictures used</em>. The numbers in <code>L · S · B</code> start from 0. Point at the bin and its tooltip gives the layer, section and bin as the <strong>Bins</strong> page numbers them.</li>
  <li><strong>Warnings</strong>: if something went wrong with the piece, the names of the problems in orange. The sentences are on the piece's own page.</li>
  <li><strong>Review</strong>: at the right of any piece that can be reviewed. How it works is on the <a href="{{ '/sorter/tracked-piece/' | relative_url }}#review-a-piece">piece page</a>.</li>
  <li><strong>Open the piece</strong> (the arrow, or clicking the pictures): opens the <a href="{{ '/sorter/tracked-piece/' | relative_url }}">piece page</a>. Back there returns you to this list with its filters, page and scroll position.</li>
  <li><strong>Scratch reclassify</strong> (the flask button): for pieces the machine still has in memory. Pick crops and run them through Brickognize again as a test. Nothing is recorded and sorting is not affected.</li>
</ul>

A piece that was never identified, has no picture and cannot be reviewed shows as one short line instead.

## Incidents

An **incident** is a time the machine stopped or held something and asked for attention, such as a piece stuck on the classification channel or a motor that stalled. This view is the log of them. It only lists: you cannot resolve an incident from here. The kinds are in the [happy path and incident inventory]({{ '/sorter/happy-path-incident-inventory/' | relative_url }}); here each kind is written in sentence case, so `exit_stuck` reads **Exit stuck**.

The row of figures at the top shows **Total incidents**, **Currently active** (with <em>awaiting the operator</em> when above zero), **Distinct kinds** and **Most frequent**.

The **Incidents** panel lists them newest first, 20 to a page. Narrow it with **Kind** (**All kinds** or one that has happened) and **Status** (**Any status**, **Active** or **Resolved**). The columns are:

<ul class="bulleted-list">
  <li><strong>When</strong>: when it was raised.</li>
  <li><strong>Kind</strong> and <strong>Channel</strong>: what it was, and which channel it concerned.</li>
  <li><strong>Status</strong>: <strong>Active</strong> or <strong>Resolved</strong>.</li>
  <li><strong>Resolved by</strong>: <strong>Operator</strong> (someone cleared it), <strong>Auto</strong> (the machine cleared it), or <strong>Superseded</strong> (a newer incident replaced it).</li>
  <li><strong>Duration</strong>: how long it took to clear.</li>
  <li><strong>Message</strong>: the machine's message to the operator. It is cut to one line; point at it for the whole text.</li>
</ul>

Below the table, three charts: **Incidents per day** (last year), **By channel** (all time), and **Frequency and resolution time** (each kind with its count and its average time to resolve).

A frequent kind with a long average time is where the machine loses the most time. Settings has a separate **Incidents** page for how each kind is handled.

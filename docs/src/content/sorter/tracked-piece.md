---
layout: default
title: The piece page
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-tracked-piece
kicker: SorterOS — Operate
author: jensr80
lede: Everything the machine recorded about one piece, from the photos it took to the bin it chose. Use it to work out why a piece went where it did, and to tell the machine when it got a piece wrong.
permalink: /sorter/tracked-piece/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the exact look of each
  panel has not been checked against a real one.
---

The piece page is the full record of a single piece. Reading it does not change anything on the machine. The one thing you can do here that is saved is [review the piece](#review-a-piece), and the **Scratch reclassify** test, which is not saved.

## Open it

<ul class="bulleted-list">
  <li>On the <strong>Pieces</strong> tab of <a href="{{ '/sorter/records/' | relative_url }}#pieces">Records</a>, click a piece's pictures or press the arrow button (<strong>Open the piece</strong>). <strong>Back to the records</strong> then returns you to the list with its filters, page and scroll position.</li>
  <li>On the dashboard, click a piece in <strong>Recent pieces</strong>.</li>
  <li>Go straight to <code>/tracked/</code> followed by the piece's id. The page title is <strong>Piece</strong> and the first 8 characters of the id. You can paste a piece id into the search on the <strong>Pieces</strong> tab to find it.</li>
</ul>

Opening `/tracked` with no id takes you to Records.

<div class="img-placeholder">Screenshot of a piece page: the header, the top card with the burst frames and facts, the review at the right, and the closed detail panels below.</div>

## What you see depends on how recent the piece is

<ul class="bulleted-list">
  <li><strong>A piece the machine still has in memory</strong> shows every panel on this page. While it is still moving through the machine the page keeps itself up to date as new photos and results arrive.</li>
  <li><strong>An older piece</strong> (from before the last restart, or aged out of memory) shows a shorter page built from what was saved: the top card, the problems, the predictions, <strong>Other channels</strong> and <strong>Record</strong>. <strong>Classification requests</strong>, <strong>Pricing</strong>, <strong>Lifecycle timeline</strong>, <strong>Arrival snapshot</strong>, <strong>Scratch reclassify</strong> and <strong>Raw JSON</strong> are not there.</li>
  <li><strong>No trace of this piece</strong> means the machine has no memory, record or stored picture of that id.</li>
  <li><strong>This piece did not load</strong> means the machine did not answer. Check the connection and open the page again.</li>
</ul>

## The header

**Back to the records**, the title **Piece** with the short id, and badges:

<ul class="bulleted-list">
  <li><strong>Distributed</strong> or <strong>Distributing</strong>: how far through the machine the piece got (shown for a piece still in memory). Neither shows for a piece that never got that far.</li>
  <li>A status badge: <strong>Classified</strong>, <strong>Unidentified</strong> (the identification found no usable match), <strong>ID failed</strong> (the request failed, so it was never identified), <strong>Multi drop</strong> (several pieces dropped together and were rejected), <strong>Pending</strong> or <strong>Classifying</strong>.</li>
  <li><strong>Timed out</strong>: the piece went silent without ever reaching the distributed stage.</li>
</ul>

## The top card

The card you came for. From left to right:

<ul class="bulleted-list">
  <li><strong>Frames.</strong> A line says how many frames there are, for example <em>9 frames from C4. Tinted frames produced the result.</em> Each small tile is one photo the camera took of the piece on the classification channel (C4). A <strong>tinted</strong> tile was sent to Brickognize in the request whose answer the piece took. The corner tags give the channel (bottom left) and a sharpness number (top right, when measured). Point at a tile to enlarge it with its burst number, time and whether it was used; click it to open it full size. If there are none, the card says <strong>No burst frames for this piece.</strong></li>
  <li><strong>Name.</strong> The part's name and number. A piece with no part is named for what became of it: <strong>Waiting for the result</strong>, <strong>Several pieces dropped together</strong>, <strong>Identification failed</strong>, <strong>Not identified</strong> or <strong>Unidentified piece</strong>.</li>
  <li><strong>Facts.</strong>
    <ul class="bulleted-list">
      <li><strong>Mold</strong>: which service identified the part, and how sure it was.</li>
      <li><strong>Color</strong>: the color, which service gave it, and how sure it was. Mold and color can come from different services, so each has its own percentage.</li>
      <li><strong>Category</strong>: the category the sorting profile put the part in.</li>
      <li><strong>Bin</strong>: the layer, section and bin it was sent to, written <code>L0 · S1 · B1</code>, then its stage. These numbers start from 0, so <code>L0 · S1 · B1</code> is layer 1, section 2, bin 2 as the <strong>Bins</strong> page numbers them. For a piece that was not identified and has no recorded bin, it reads <strong>discard bin</strong>.</li>
      <li><strong>Value</strong> (when known) and <strong>Seen</strong> (when the machine first saw it).</li>
    </ul>
  </li>
  <li><strong>Brickognize.</strong> The catalog picture of the part the piece was identified as. Click it to enlarge.</li>
</ul>

The review sits at the far right on a wide screen, or under the card on a narrower one.

### Review a piece

The review appears only when a Brickognize result was captured for the piece. It is three questions, each answered with one click and saved at once.

<ul class="bulleted-list">
  <li><strong>Part correct?</strong> Press <strong>Yes</strong> or <strong>No</strong>. This is about the type of part only, not its color.</li>
  <li><strong>Color correct?</strong> It shows the predicted color. Press <strong>Yes</strong> if it is right. If not, press <strong>No</strong>, which opens a list of colors with the most likely first and then all of them, with the predicted one marked <em>Predicted</em> and its percentage. Choose the right one, then press <strong>Confirm</strong> and its name (or <strong>Cancel</strong>). Afterwards the button shows the color you chose. With no color predicted, the button reads <strong>Pick</strong>.</li>
  <li><strong>Report an issue.</strong> A row of icons for what was wrong with the photos: <strong>Not LEGO</strong>, <strong>Multiple pieces in frame</strong>, <strong>No piece in frame</strong>, <strong>Assembly</strong>, <strong>Pieces entangled</strong> and <strong>Blurry</strong>. Point at an icon for its name. Click to turn one on, click again to turn it off. Any number can be on.</li>
</ul>

A <strong>Sent</strong> badge beside an answer means it was passed on to Brickognize as feedback on its identification. The issue flags are not sent to Brickognize; they are saved with the piece. See [What leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}) for what is shared beyond the machine.

If something goes wrong the review says so under the rows: <strong>Saved, but Brickognize did not accept it</strong> with the reason (your answer is still saved), or <strong>Could not reach the machine; nothing was saved.</strong> When the list of likely colors cannot be ranked the list says why, for example <em>By color alone: the machine cannot reach Hive.</em>

## Problems

If anything went wrong with the piece, a yellow box lists each problem, oldest first: a bold name, the machine's own sentence about it, and the time of day. It is absent for a piece with no problems. The names:

<ul class="bulleted-list">
  <li><strong>Timed out</strong>: it never reached a bin. It went without an update for too long, so it was written off. The sentence says what it was doing when it went quiet.</li>
  <li><strong>Lost by the camera</strong>: the camera lost track of it on the channel and nothing picked it up again, so where it went is not known and no bin counts it.</li>
  <li><strong>Double feed</strong>: it landed with, against or touching another piece, so it could not be photographed alone. It went to misc.</li>
  <li><strong>Second piece came in late</strong>: another piece came onto the channel just after this one, while this one was being turned off the drop zone. Both went to misc as a double feed.</li>
  <li><strong>Never photographed</strong>: the camera first saw it somewhere other than the drop zone, so it was never photographed or identified. It went to misc.</li>
  <li><strong>Held for misc</strong>: it went to misc instead of its bin because a lost double-feed piece was still loose on the channel, so every door stayed open for a couple of turns.</li>
  <li><strong>Didn't fall</strong>: it was still on the channel after the turn meant to drop it into its bin. It was counted as dropped anyway.</li>
  <li><strong>Pushed off the exit</strong>: it was still at the exit after it should have dropped, so the channel turned to push it off. The sentence gives the try number.</li>
  <li><strong>Came back around</strong>: it came back around after the same part in the same color was dropped. That is one piece seen twice, so this record is not counted and the machine stopped for it.</li>
  <li><strong>Swept off</strong>: the classification channel stopped making progress, so the machine turned it with every door open to clear it. The piece went to the bucket, not its bin.</li>
  <li><strong>Identification failed</strong>: the request failed or did not answer in time, so the piece went to misc unidentified.</li>
  <li><strong>Color model didn't answer</strong>: the color model did not answer, or answered without a color, so Brickognize's color was used.</li>
</ul>

On the Records list only the names are shown; the full sentences are here.

## Predictions

The **Predictions** panel lists every identification request made for the piece, grouped by where it came from. **While sorting** is what the machine asked as the piece went through. Any other group is a later run over the piece's stored pictures. The panel header counts the requests and sources.

Each request shows:

<ul class="bulleted-list">
  <li>What was asked (<strong>Combined (fused set)</strong>, <strong>Single burst frame</strong>, or the name of the model) and who answered (<strong>Brickognize</strong> or <strong>basically color model</strong>, with the first 8 characters of the model's hash).</li>
  <li>Under <strong>Part</strong> and <strong>Color</strong>, its top three answers with a percentage. The one the piece took is marked <strong>Applied</strong>.</li>
  <li><strong>Saw</strong>: small pictures of the images it was given, named <em>Burst</em> or <em>Link</em> with a number (and channel for link images). It says <strong>Not recorded</strong> or <strong>No stored images</strong> where that applies. A picture that is no longer on the machine shows as a labelled tag you can point at.</li>
</ul>

The panel is absent for pieces classified before predictions were kept.

## Details

Under the predictions is a list of panels. Each is closed until you click its title, and its title carries a one-line summary.

<ul class="bulleted-list">
  <li><strong>Classification requests.</strong> Summary: how many requests were sent in parallel and which was applied. The requests ran at the same time, not as retries. The most confident one that found a match is the one applied (marked <strong>Applied</strong> and tinted). Each row gives its name, how many burst images it sent, its outcome (<em>error</em>, <em>no match</em>, or the part number and percentage), the part and color, and how long it took. Click a row to see <strong>Sent</strong>, the crops that were sent (<strong>Crops aged out</strong> if they are gone), and <strong>Result</strong>, the reference picture, part, match percentage and color, or the error or <strong>No match</strong>. Comparing a combined request against a single clean frame shows when one blurry frame confused the answer.</li>
  <li><strong>Other channels.</strong> Views of the same physical piece from the C2 and C3 channels upstream, found by matching, with the most probable match first. Each tile shows its channel, <strong>Used</strong> if it was fused into the request, its sharpness, and its match probability (for example <em>82% match</em>). These are the matcher's guesses, not confirmed pictures of the piece. With none, it says <strong>No upstream views of this piece.</strong></li>
  <li><strong>Pricing.</strong> Shown when price data exists. The moving average, which routing uses, is the first available of four BrickLink figures with sold new preferred. A table lists <strong>Sold · Used</strong>, <strong>Sold · New</strong>, <strong>Listed · Used</strong> and <strong>Listed · New</strong> with <strong>Avg</strong>, <strong>Weighted avg</strong>, <strong>Min</strong>, <strong>Max</strong>, <strong>Qty</strong> and <strong>Lots</strong>. An <strong>Approximate</strong> warning means there is no market data for this exact print, so the price of its base mold is shown.</li>
  <li><strong>Lifecycle timeline.</strong> The moments the piece passed, with the time of each and the time since the first: <strong>Created / first seen</strong>, <strong>Feeding started</strong>, <strong>First carousel sighting</strong>, <strong>Carousel confirmed</strong>, <strong>Carousel rotate started</strong>, <strong>Carousel rotated</strong>, <strong>Snapping started</strong>, <strong>Snapping completed</strong>, <strong>Classified</strong>, <strong>Distributing</strong>, <strong>Target bin selected</strong>, <strong>Distribution motion</strong>, <strong>Positioned over bin</strong> and <strong>Distributed</strong>. Only events that happened are listed. The timeline's "carousel" is the classification channel.</li>
  <li><strong>Record.</strong> For a piece in memory: its <strong>Stage</strong>, <strong>Tracker</strong> number, <strong>Source view</strong> and <strong>Last update</strong>. For an older piece: the <strong>Run</strong> (the id of the machine session that recorded it) and when it was <strong>Recorded</strong>.</li>
  <li><strong>Arrival snapshot.</strong> The full classification-channel frame at the moment the piece dropped in. Click <strong>At arrival</strong> to enlarge it.</li>
  <li><strong>Scratch reclassify.</strong> Pick some of the piece's crops (those that were used start selected, at most 8) and press <strong>Run Brickognize</strong> to see what Brickognize says about them now. It is marked <strong>Testing only</strong>: it is not recorded and has no effect on sorting.</li>
  <li><strong>Raw JSON.</strong> Every field the machine holds for the piece, as text.</li>
</ul>

## Work out why a piece went where it did

<ol class="numbered-steps">
  <li>Read the status badge and the problems box. When the machine recorded a reason a piece went to misc or the bucket (a double feed, a failed identification, a sweep), it is written there.</li>
  <li>Check <strong>Category</strong> and <strong>Bin</strong> in the top card. The sorting profile sets the category, and the machine assigns categories to bins. How is in <a href="{{ '/sorter/bins-and-profiles/' | relative_url }}">Bins and profiles</a>.</li>
  <li>If the part looks wrong, open <strong>Predictions</strong>. See which request was <strong>Applied</strong> and what the others said. A single request that disagrees with the rest points at one bad frame.</li>
  <li>Look at the tinted frames in the top card. Blurred or empty frames, or a low sharpness number beside the others, explain a poor identification. Mark them with the <strong>Blurry</strong>, <strong>No piece in frame</strong> or <strong>Multiple pieces in frame</strong> issues so the mistake is on record.</li>
  <li>If the color looks wrong, read <strong>Color</strong> for the service that gave it. A <strong>Color model didn't answer</strong> problem means Brickognize's color was used instead.</li>
  <li>If the piece went somewhere unexpected despite a good identification, open <strong>Raw JSON</strong> and look for <code>high_value_routed</code> (its price cleared the profile's high-value threshold, so it was rerouted), <code>not_in_inventory</code> (the part and color are not in the active inventory) and <code>too_big</code> (it exceeded the oversize limit and went to the misc bottom bin). <strong>Pricing</strong> shows the price routing used.</li>
  <li>If it took a long time, open <strong>Lifecycle timeline</strong>. A long gap between two events is where it waited.</li>
  <li>Answer the review. Your answers are how a wrong identification gets recorded.</li>
</ol>

To find other pieces that went the same way, go back to [Records]({{ '/sorter/records/' | relative_url }}#pieces) and filter by **Status**, **Bin** or **Run or lot**.

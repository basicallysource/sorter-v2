---
layout: default
title: Reviewing samples
type: how-to
audience: operator
applies_to: Hive review queue, machine Records page
section: hive
owner: hive
slug: hive-review-samples
kicker: Hive — How-to
lede: Which samples are worth your votes, how reviewing on Hive differs from correcting pieces on the Records page, and what to check when the review queue is empty.
permalink: /hive/review-samples/
warning: >-
  **AI-generated first draft.** Written from Hive's and the machine UI's source and from
  community discussion, not from clicking through the flow start to finish. Correct it as
  you use it.
---

Samples are camera images your machine uploads to Hive while it runs. If that is new to you, [How Hive works]({{ '/hive/how-hive-works/' | relative_url }}) explains what a sample is first. Each one has outlines drawn around the pieces in it. Reviewers vote **accept** or **reject** on those outlines. A sample needs 3 agreeing votes to count as accepted. A new piece-finding model is trained from accepted samples.

## Which samples to review first

<ul class="bulleted-list">
  <li><strong>Samples that have fewer than 3 votes.</strong> The review queue only serves these, so any vote you give there counts toward a result.</li>
  <li><strong>Conflicts.</strong> When votes disagree, the sample stays stuck until someone changes a vote. Open <strong>Samples</strong> and filter the status to <strong>Conflict</strong>. Look at the outlines again before you vote.</li>
  <li><strong>Clean outlines.</strong> Accept a sample when every piece on the target c-channel has its own tight outline. Accept it too when the channel is empty. An outline that is almost right is a reject. So are two touching pieces in one outline.</li>
</ul>

When you are unsure, skip. Skipping costs nothing, and a wrong vote can send a sample into conflict.

The review screen works from the keyboard: up accepts, down rejects, right skips and left goes back.

## Records page or Hive

These are two different jobs, not the same job in two places.

<ul class="bulleted-list">
  <li><strong>Records page, in your machine's own UI.</strong> You check pieces your machine actually sorted. Confirm or reject the part it named, and correct the colour. The answer goes back to the part-recognition service as feedback on that one result. Only pieces with a recognition result can be corrected. It does not count toward the 3 votes on Hive.</li>
  <li><strong>Hive review.</strong> You judge the outlines on camera samples from the channels, the classification chamber and so on. Votes here decide whether a sample goes into the training set. That set trains the model that finds pieces in the camera picture.</li>
</ul>

If your aim is a better piece-finding model, review on Hive. If your aim is to correct what your own machine got wrong on a piece it sorted, use the Records page.

## No samples to review

Work down this list.

<ol class="numbered-steps">
  <li><strong>Your role.</strong> Voting needs the <strong>reviewer</strong> role. A normal Hive account sees only the samples from its own machines and cannot vote. The Basically team grants reviewer access. Ask in the <code>#sample-review</code> channel on Discord.</li>
  <li><strong>Your machine.</strong> New samples appear only while a machine is running with sampling switched on. If your machine is offline or not uploading, nothing new arrives.</li>
  <li><strong>The filters.</strong> The default queue hides four kinds of sample: ones you already voted on, ones with 3 votes, ones whose outlines have not been checked yet, and badly exposed shots. The <strong>Unreviewed</strong> and <strong>Conflict</strong> status filters on <strong>Samples</strong> can still show work when the main queue looks empty.</li>
</ol>

## Related

<ul class="bulleted-list">
  <li><a href="{{ '/hive/' | relative_url }}">Hive overview</a></li>
  <li><a href="{{ '/hive/first-profile/' | relative_url }}">Build your first sorting profile</a></li>
</ul>

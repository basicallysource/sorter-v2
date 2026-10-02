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

Samples are camera images your machine uploads to Hive while it runs. If that is new to you, [How Hive works]({{ '/hive/how-hive-works/' | relative_url }}) explains what a sample is first. Reviewers vote **accept** or **reject** on the boxes drawn on each one. A sample needs 3 agreeing votes to count as accepted, and the accepted samples are what a new vision model is trained from.

## Which samples to review first

<ul class="bulleted-list">
  <li><strong>Samples that have fewer than 3 votes.</strong> The review queue only serves these, so any vote you give there counts toward a result.</li>
  <li><strong>Conflicts.</strong> When votes disagree, the sample stays stuck until someone changes a vote. Open <strong>Samples</strong> and filter the status to <strong>Conflict</strong>, then re-read the boxes carefully before you vote.</li>
  <li><strong>Cleanly boxed samples.</strong> Accept a sample when every piece on the target c-channel has its own tight box, or when the channel is empty. A box that is almost right is a reject. Two touching pieces in one box is a reject.</li>
</ul>

When you are unsure, skip. Skipping costs nothing, and a wrong vote can send a sample into conflict.

The review screen works from the keyboard: up accepts, down rejects, right skips and left goes back.

## Records page or Hive

These are two different jobs, not the same job in two places.

<ul class="bulleted-list">
  <li><strong>Records page, in your machine's own UI.</strong> You check pieces your machine actually sorted. Confirm or reject the part it named, and correct the colour. The answer goes back to the part-recognition service as feedback on that one result, and only pieces that have a recognition result attached can be corrected. It does not count toward the 3 votes on Hive.</li>
  <li><strong>Hive review.</strong> You judge the boxes on camera samples from the channels, the classification chamber and so on. Votes here are what decide whether a sample goes into the training set for the machine's own vision model.</li>
</ul>

If your aim is a better detection model, review on Hive. If your aim is to correct what your own machine got wrong on a piece it sorted, use the Records page.

## No samples to review

Work down this list.

<ol class="numbered-steps">
  <li><strong>Your role.</strong> Voting needs the <strong>reviewer</strong> role. A normal Hive account can see only the samples from its own machines and cannot submit votes. Reviewer access is granted by the Basically team, so ask in the <code>#sample-review</code> channel on Discord.</li>
  <li><strong>Your machine.</strong> New samples appear only while a machine is running with sampling switched on. If your machine is offline or not uploading, there is nothing new for it.</li>
  <li><strong>The filters.</strong> The default queue hides samples you already voted on, samples that already have 3 votes, boxes that have not been checked yet, and badly exposed shots. The <strong>Unreviewed</strong> and <strong>Conflict</strong> status filters on <strong>Samples</strong> can still show work when the main queue looks empty.</li>
</ol>

## Related

<ul class="bulleted-list">
  <li><a href="{{ '/hive/' | relative_url }}">Hive overview</a></li>
  <li><a href="{{ '/hive/first-profile/' | relative_url }}">Build your first sorting profile</a></li>
</ul>

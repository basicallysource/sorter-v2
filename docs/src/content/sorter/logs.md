---
layout: default
title: Logs
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-logs
kicker: SorterOS — Operate
author: jensr80
lede: Read the machine's own log in the browser, narrowed to the errors, warnings or text you are after. Use it when something went wrong and the dashboard does not say why.
permalink: /sorter/logs/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording on screen has
  not been checked against a real machine.
---

The **Logs** page shows the end of the log file the backend is writing, with a search box and a level filter on top. It only reads. Opening it changes nothing on the machine.

## Open it

There is no entry for it in the top menu. Go to `/logs` on the machine's address (`http://sorter.local/logs` on the SorterOS image).

<div class="img-placeholder">Screenshot of the Logs page with the Machine Backend source selected, the search box and level filter above the log lines, and the count badges.</div>

## Turn the log file on

The page reads a log file, not the system journal. A standard install does not write that file, so both sources read **Unavailable** and the right-hand panel says *No log source is selected*. To switch it on:

<ol class="numbered-steps">
  <li>Add the line <code>export DUMP_BACKEND_LOGS=1</code> to the <code>.env</code> file in the <code>software</code> folder of the sorter-v2 checkout on the machine.</li>
  <li>Restart the whole backend service so it reads the file again: <strong>Restart the machine</strong> in the ⋯ System menu does it, or see the full restart in <a href="{{ '/sorter/dev-flow/' | relative_url }}">Dev flow</a>. <strong>Restart the backend</strong> in the same menu is not enough, because it keeps the old environment.</li>
  <li>Open the Logs page and press <strong>Refresh</strong>.</li>
</ol>

The backend then starts a new log file in the `logs` folder each time it starts, named after the date and time. It is off by default because these files can grow very large at the default level and have filled SD cards. To keep that in check the backend deletes the oldest log files once they total more than 1 GB.

Which lines get written depends on `DEBUG_LEVEL` in the same `.env`. The installer and the SorterOS image set it to `2`, which writes errors, warnings and info. Debug lines are written only at `3` or higher, so with the stock value the **Debug only** filter below finds nothing.

## The sources

The **Sources** list on the left has two entries. Each shows its size, the file it is reading, and when that file was last updated.

<ul class="bulleted-list">
  <li><strong>Machine Backend:</strong> the current sorter runtime and backend process output. This is the one you want. It is selected automatically when it is available.</li>
  <li><strong>Machine API:</strong> logs of a standalone, API-only machine process, if one exists. It is <strong>Unavailable</strong> unless such a process has written a log.</li>
</ul>

An <strong>Unavailable</strong> source is greyed out and cannot be selected. Click an available one to read it. The panel on the right is headed with its name and the full path of the file.

## Controls

The row at the top right of the page:

<ul class="bulleted-list">
  <li><strong>Lines:</strong> how many of the newest lines to load: <strong>200</strong>, <strong>400</strong> (the default), <strong>800</strong> or <strong>1500</strong>. The machine reads at most the last 512 KB of the file, so on a chatty log you can get fewer lines than you asked for.</li>
  <li><strong>Auto refresh:</strong> off by default. When on, the page reloads the log every 3 seconds, and rechecks the list of sources every 30 seconds. Switch it on to watch the machine live, off to read without the page moving under you.</li>
  <li><strong>Wrap lines:</strong> on by default. When off, each line stays on one row and scrolls sideways.</li>
  <li><strong>Refresh</strong> reloads the sources and the log once.</li>
</ul>

The page does not update on its own unless **Auto refresh** is on. Lines appear oldest first, so the newest is at the bottom.

## Read a line

Lines the backend wrote in its usual form, `[date time] [LEVEL] message`, are split into a timestamp, a colored badge and the message. A line that is not in that form, such as the extra lines of an error trace or text from another program, gets no timestamp and the **Other** badge.

<ul class="bulleted-list">
  <li><strong>Error</strong> (red): lines tagged <code>ERROR</code> or <code>CRITICAL</code>.</li>
  <li><strong>Warning</strong> (amber): lines tagged <code>WARN</code> or <code>WARNING</code>.</li>
  <li><strong>Info</strong> (blue) and <strong>Debug</strong> (grey): lines tagged <code>INFO</code> and <code>DEBUG</code>.</li>
  <li><strong>Other</strong> (grey): everything else.</li>
</ul>

## Search and filter

Above the lines:

<ul class="bulleted-list">
  <li><strong>The search box</strong> keeps only lines containing what you type, ignoring capitals. It looks at the whole line, so you can search a message, an error name, a part ID or a camera name. It searches only the lines loaded, so raise <strong>Lines</strong> to search further back.</li>
  <li><strong>Level</strong> offers <strong>All levels</strong>, <strong>Errors only</strong>, <strong>Warnings only</strong>, <strong>Info only</strong>, <strong>Debug only</strong> and <strong>Other or raw only</strong>. It combines with the search: a line must pass both.</li>
  <li><strong>The badges</strong> show <strong>N matching lines</strong> after your filters, then <strong>Errors</strong>, <strong>Warnings</strong> and <strong>Info</strong> counts for all the loaded lines. The counts do not change when you filter.</li>
</ul>

When nothing passes, the panel says *No log lines match the current filters.*

## What to do with it

<ul class="bulleted-list">
  <li><strong>Something just failed.</strong> Press <strong>Refresh</strong>, set <strong>Level</strong> to <strong>Errors only</strong>, and read from the bottom. Then set it back to <strong>All levels</strong> and find the same time to see what the machine was doing around the error.</li>
  <li><strong>A specific piece or camera misbehaves.</strong> Search for its part ID or camera name.</li>
  <li><strong>Watching a run.</strong> Switch <strong>Auto refresh</strong> on and watch the <strong>Errors</strong> and <strong>Warnings</strong> counts. A rising count is worth a look.</li>
  <li><strong>Reporting a problem.</strong> Note the machine's state from the <a href="{{ '/sorter/dashboard/' | relative_url }}">dashboard</a> and copy the relevant lines from the page. Start from <a href="{{ '/sorter/troubleshooting/' | relative_url }}">SorterOS troubleshooting</a>, which lists known symptoms and their fixes.</li>
</ul>

If the page shows a red banner, the machine could not be reached or did not return the log. The banner carries the reason.

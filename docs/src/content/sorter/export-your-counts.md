---
layout: default
title: Exporting what the machine sorted
type: how-to
section: sorter
slug: sorter-export-counts
kicker: SorterOS — Operations
lede: Every piece the machine classifies is recorded. Download the list as a CSV to use as an inventory.
permalink: /sorter/export-counts/
---

Each classified piece is saved as a record: the part, the colour, how confident the identification was, and the bin it was sent to. Three **Export CSV** buttons in the UI turn those records into files you can open in a spreadsheet.

## Every piece, one row each

Open **Records**, and click **Export CSV** next to **Pieces**. You get one row per piece with:

- the part number and name, and the colour number and name
- the part and colour confidence
- the bin it went to (`bin_x`, `bin_y`, `bin_z`)
- when it was seen and when it was recorded
- the run it belongs to
- a link to the picture used to identify it

To count how many of each part you have, group the rows by `part_id` and `color_id` in your spreadsheet.

The button exports everything. To export only part of it, add filters to the address `/api/pieces/export.csv` in your browser: `run_id`, `status`, `part_id`, `color_id`, `date_from` and `date_to`.

Pieces the machine could not identify are in the file too. Filter on `classification_status` equal to `classified` before you total anything, or your inventory will count pieces that have no part number.

## What is in the bins now

Open **Bins** and click **Export CSV**. This lists the pieces currently sitting in the bins, with the layer, section and bin each one is in, and the profile it was sorted under. It reflects the bins as they are now, so emptying a bin changes the next export.

**Snapshots** on the same page saves the bin contents at a moment in time. Each snapshot can be exported the same way, so you can keep a record before you empty the bins.

## Daily totals

On **Records**, **Export CSV** on **Daily activity** gives one row per day: seconds powered, seconds spent sorting, and the number of pieces seen, classified and distributed. It covers the last year.

## Which one to use

- **How many of each part have I sorted?** The Pieces export.
- **What is in this bin right now?** The Bins export.
- **How much has the machine run?** The daily export.

---
layout: default
title: Log in over SSH
type: how-to
section: sorter
slug: sorter-ssh
author: jensr80
audience: self-hosting operator
applies_to: sorteros v4.x
last_verified: 2026-11-07
kicker: SorterOS - Under the hood
lede: Open a command line on the machine from your computer, using SSH.
permalink: /sorter/ssh/
---

SSH gives you a command line on the machine's Linux system from another
computer on the same network. Everything under Under the hood assumes you can
do this.

## Install an SSH client

- **Windows:** follow Microsoft's
  [SSH in Windows Terminal](https://learn.microsoft.com/en-us/windows/terminal/tutorials/ssh)
  tutorial to get a client.
- **macOS and Linux:** `ssh` is already installed.

## Log in

Open a terminal on your computer and run one of:

```bash
ssh root@sorter.local
```

```bash
ssh orangepi@sorter.local
```

- `root` can change anything on the machine.
- `orangepi` is the normal user. The software lives in its home folder,
  `/home/orangepi/sorter-v2`.
- The default `root` password is in
  [Install the SorterOS image]({{ '/sorter/installation/sorter-os/' | relative_url }}).
- The first time, SSH asks whether to trust the machine. Type `yes`.

If you gave the machine another hostname in SorterOS Setup, use that instead of
`sorter`.

To leave, type `exit`.

## Next

What you can change once you're in: [The Linux system]({{ '/sorter/linux-system/' | relative_url }}).

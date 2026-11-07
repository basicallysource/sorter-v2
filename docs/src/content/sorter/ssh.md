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
- **macOS:** `ssh` is already installed.
- **Linux:** `ssh` comes from the `openssh-client` package. Check your
  distribution's documentation for how to install it.

## Log in

Open a terminal on your computer and run:

```bash
ssh root@sorter.local
```

- The default password is `orangepi`.
- The first time, SSH asks whether to trust the machine. Type `yes`.
- `root` can change anything on the machine.

If you gave the machine another hostname in SorterOS Setup, use that instead of
`sorter`.

To leave, type `exit`.

## Next

What you can change once you're in: [The Linux system]({{ '/sorter/linux-system/' | relative_url }}).

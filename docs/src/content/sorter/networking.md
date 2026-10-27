---
layout: default
title: Networking
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-networking
kicker: SorterOS — Operate
author: reveryx
lede: Point the UI at a machine, put the machine on a Wi-Fi network, and join or switch its Tailscale network, all from Settings. Also what to do when the page cannot reach the machine.
permalink: /sorter/networking/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording of the
  messages on the page has not been checked against a real one.
---

**Settings**, then **Networking** has three panels: **Connection** (how this page reaches the machine), **Wi-Fi** and **Tailscale** (the machine's own networks). Opening it changes nothing. Changes happen only when you press **Connect**, **Apply** or an item in the repair menu.

<div class="img-placeholder">Screenshot of Settings > Networking with the Connection, Wi-Fi and Tailscale panels.</div>

The **Wi-Fi** and **Tailscale** panels act on the machine this page is connected to. The page remembers the last Wi-Fi and Tailscale status it got from each machine for as long as the app stays open, so it opens on that and refreshes behind it.

## Connection

This is the machine the browser is talking to, not a network setting on the machine.

<ul class="bulleted-list">
  <li><strong>Address</strong> is the machine's backend, written as <code>ws://host:8000/ws</code>. Type one and press <strong>Connect</strong> to add that machine.</li>
  <li><strong>Connected machines</strong> lists every machine this page is connected to, with its name and address. A green dot means connected, a red dot means the connection is down. Press a machine to select it: the rest of Settings, including the Wi-Fi and Tailscale panels, then acts on that machine.</li>
  <li><strong>Disconnect</strong> on a machine's row closes this page's connection to it. It does not switch the machine off or change anything on it.</li>
</ul>

## Join a Wi-Fi network

The **Wi-Fi** panel lists the machine's Wi-Fi adapters and the networks they can see. It is for networks that need nothing more than a password. A network that asks for a username as well (many office and school networks) cannot be joined here, and networks that hide their name are not listed. Use Ethernet for those.

<ol class="numbered-steps">
  <li>Look under <strong>Adapters</strong>. Each adapter shows its name, what it is connected to (or its state), its MAC address and, when connected, its IP address. If the machine has more than one adapter, a <strong>Connect using</strong> menu appears: pick the adapter to join with. It starts on a connected adapter, or the first one.</li>
  <li>Under <strong>Networks</strong>, press <strong>Scan</strong> if your network is not listed. The list shows signal strength, a lock for a network with a password, and <strong>Connected</strong> beside the one in use, which is always first. When you open the page it shows the last scan, and scans again behind it if that scan is more than a minute old. A scan takes a few seconds.</li>
  <li>Press the network. A row opens under it: type the password in the <strong>Password for</strong> field, or, for an open network, read <strong>An open network: no password.</strong></li>
  <li>Press <strong>Connect</strong> (it reads <strong>Connect with</strong> and the adapter name when an adapter is chosen). It stays disabled until a password is typed for a secured network. The machine waits up to 45 seconds for the network to accept it and hand out an address.</li>
  <li>A green message means it joined, and the adapter's row now shows the network and its IP address. A red message is the error the machine's network manager gave back: a wrong password, or <strong>Timed out connecting</strong>, which means the network did not answer in time.</li>
</ol>

**Switching the network an adapter uses can drop this page** if you reached the machine through that adapter. Over Ethernet or Tailscale you stay connected. If you are on the machine's Wi-Fi, write down the new IP address from the adapter's row before you leave the old network, and see [When the page cannot reach the machine](#when-the-page-cannot-reach-the-machine).

The setup network the machine broadcasts when it has no internet (<code>SorterOS-Setup-</code> and six characters) is never shown here. It is for first boot and for recovery, see [Install the SorterOS image]({{ '/sorter/installation/sorter-os/' | relative_url }}).

If the panel instead says **NetworkManager (nmcli) isn't available on this machine, so its Wi-Fi can't be managed here**, this machine does not manage Wi-Fi through the page. **No Wi-Fi adapters found** means the machine sees no Wi-Fi hardware.

## Tailscale

Tailscale is a private network the machine can join. The panel shows one of these states at the top:

<ul class="bulleted-list">
  <li><strong>Connected</strong>, with the machine's Tailscale IP address. Below it: <strong>Hostname</strong>, <strong>Network</strong>, and <strong>Joined as</strong>. A machine joined with a tag belongs to that network rather than to a person, and its key does not expire. A machine signed in as a person has a key that expires, unless key expiry is turned off for the machine in Tailscale's admin console. Anything Tailscale itself reports as a problem is listed as <strong>Tailscale reports</strong>.</li>
  <li><strong>Not connected</strong>, with the reason under it. <strong>Waiting for approval</strong> means an admin of that Tailscale network has to approve the machine.</li>
  <li><strong>Tailscale is not installed</strong>, <strong>Installing Tailscale</strong> and <strong>The Tailscale service isn't running</strong>. SorterOS installs Tailscale by itself when it is missing, and the panel checks again every five seconds while that runs.</li>
</ul>

**Join a Tailscale network, or switch to another:**

<ol class="numbered-steps">
  <li>Make an auth key in Tailscale's admin console (<code>tailscale.com/admin/settings/keys</code>). Use a key you made yourself or got from someone you fully trust: the panel warns that the owner of that network gets SSH access to the machine and access to your local network.</li>
  <li>Paste it into <strong>Auth key</strong> and press <strong>Apply</strong>. The field hides what you type. <strong>Apply</strong> is disabled until there is a key, and while Tailscale is not installed or another Tailscale action is running.</li>
  <li>The machine joins, or leaves its current network for the new one, at once, and can take up to 30 seconds. A green message names the network it joined and as what. The key is cleared from the field.</li>
</ol>

If it fails, the red message says why. If the machine cannot reach Tailscale's servers, the message says so: something on that network (a router, firewall or DNS filter) may be blocking Tailscale. If it says the sorter software isn't allowed to change Tailscale, it gives the one command to run on the machine, then apply the key again. A key rejected at first boot is covered in [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}#first-boot).

### The repair menu

The **...** button (**Repair Tailscale**) opens three items. **Restarting or repairing Tailscale can briefly interrupt your connection** if you reached the machine over Tailscale.

<ul class="bulleted-list">
  <li><strong>Restart the service</strong> restarts the Tailscale service on the machine.</li>
  <li><strong>Install or repair Tailscale</strong> downloads and reinstalls it. It needs internet, and a green message appears when it finishes. If it fails, the message says so and the same item tries again.</li>
  <li><strong>Clear the previous sign-in</strong> asks you to confirm, then disconnects the machine from its Tailscale network and removes any saved setup key. If you opened this page through Tailscale it may stop answering. Open Settings on the machine's local network and enter a new auth key to connect again.</li>
</ul>

The first two are greyed out when the machine cannot repair itself (the panel then says **Service repair isn't available on this machine**). If Tailscale is not installed and cannot be installed from here, the panel gives the install command to run on the machine.

## When the page cannot reach the machine

If the page has had no answer from the machine for about six seconds, a box appears: **The backend is not responding**. It closes by itself when the machine answers again. Two buttons:

<ul class="bulleted-list">
  <li><strong>Check the connection</strong> retries the connection now. The page also retries on its own every few seconds.</li>
  <li><strong>Restart the backend</strong> asks the machine to restart its software and waits for it. Check first that the machine is powered on.</li>
</ul>

Things to check, in order:

<ol class="numbered-steps">
  <li>The machine is powered on and the backend service is running. Give it a minute after power-on.</li>
  <li>The address. After a Wi-Fi change the machine has a new address, so use the one from the adapter's row, or <code>http://sorter.local</code>, and check it starts with <code>http://</code>.</li>
  <li>A cable. If a Wi-Fi change cost you the page, plug Ethernet in and reload.</li>
  <li>If the machine can no longer reach the internet, it opens its <code>SorterOS-Setup-</code> network again after about a minute. Join it from a phone to pick a network, as in <a href="{{ '/sorter/installation/sorter-os/' | relative_url }}">Install the SorterOS image</a>.</li>
</ol>

More fixes are in [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}#first-boot), and what the machine sends over the network is listed in [what leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}).

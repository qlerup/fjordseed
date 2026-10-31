# FjordSeed for Chrome

A Manifest V3 extension that hands NordicBytes and Sagmire torrent and RSS links to the normal FjordSeed dialogs. It is manually installed, not published in Chrome Web Store.

## Install and use

1. Extract the ZIP into a directory you will retain.
2. Open `chrome://extensions`, enable Developer mode and choose Load unpacked.
3. Select the directory containing `manifest.json`.
4. Open the toolbar popup, save the Seed origin, e.g. `https://seed.example.com` or `http://192.168.1.110:8099`, and grant access to that origin.
5. Sign into NordicBytes or Sagmire in Chrome. Right-click a torrent download link or an RSS-feed name and choose Send to FjordSeed.
6. The extension activates an existing matching Seed tab/window or opens a new one. Sign in if necessary. Confirm file retention/seeding in the normal dialog and Start download. Another open dialog is not overwritten; close it and select Continue in the extension.

Torrent handoff fetches only the small `.torrent` using your existing tracker login, without writing to Chrome's Downloads directory. Content starts downloading only after confirmation in Seed, through its ordinary VPN/buffer/seeding rules.

Version 1.3.0 adds a second torrent-link context menu: **Føj til torrentpakke (flere)**. Repeated selections collect a manual-download package; this option is never offered for RSS. An existing signed-in FjordSeed tab receives selections in the background without replacing an open dialog. If no matching tab exists, the first selection opens a visible tab. If sign-in is required, the extension focuses the login tab and waits before fetching or delivering the selected torrents. Delivery resumes after login.

In FjordSeed, choose **Åbn pakken** to review Freeleech and ratio information for each torrent and select common seeding settings before starting. Successful starts leave the draft; failed items remain available for retry. Drafts are stored per FjordSeed account across reloads/restarts, with limits of 50 files, 4 MiB per file and 32 MiB total. Removing a draft does not remove or stop a running torrent. The extension popup can open FjordSeed or retry/clear links still awaiting delivery. Undelivered links expire after 15 minutes and are lost when Chrome closes; already delivered drafts remain in FjordSeed. Both FjordSeed and the extension must be updated to use packages.

RSS handoff opens Add RSS feed with the full address, including private parameters. Set name, start date, filters and seeding, then save. The extension never fetches the feed; qBittorrent fetches it through VPN after activation. Feeds can be configured while the VPN is offline.

The context menu recognizes `https://nordicbytes.org/torrents/download/<number>` or the matching Sagmire URL, and feed paths under `/rss` or `/torrents/rss`, including query parameters. Chrome's Copy link address and clipboard are untouched.

## Troubleshooting and privacy

The popup shows status and allows continuing/clearing the one pending link. Links expire after 15 minutes and exist only in browser session storage until handoff/browser close. RSS secrets never enter the destination tab's URL. Clearing an extension handoff does not cancel an already saved feed/started torrent.

Tracker login redirects/errors are not forwarded as torrent files. Sign in and retry. Configure only the Seed origin, without `/login` or subpaths; close conflicting dialogs and check VPN readiness if requested.

Permissions cover NordicBytes, Sagmire and the approved Seed host. Chrome host permissions cover all ports, but handoff additionally enforces the exact configured port. No cookie API, passwords/API keys, external analytics or remote scripts are used.

For updates, replace extracted files and Reload at `chrome://extensions`. Package with `python tools/package_chrome_extension.py` from the repository root. Validate with `node --test tests/test_chrome_extension.mjs` and `python tests/browser_extension_check.py`, using isolated handoffs rather than a live tracker.

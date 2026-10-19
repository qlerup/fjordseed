# FjordSeed

A separate FjordHub seedbox with bundled qBittorrent. FjordVPN manages Proton profiles; installation starts no torrents. The interface currently uses Danish labels.

The image bundles **qBittorrent 5.2.4**, built from the official release source
with a pinned SHA-256 checksum on the same stable Alpine base as the app.
Build tools stay in a separate stage; no Alpine edge packages are used.
The first build takes longer because it compiles qBittorrent (two parallel jobs
by default; `QBITTORRENT_BUILD_JOBS` can be set as a Docker build argument).
Updating an existing installation requires rebuilding and recreating the app
(`docker compose up -d --build` for standalone installations); its worker then
uses the new image. Keep the existing data/download directories to retain
torrents, resume data and settings. For rollback, retain the previous app image
and back up the data directory before updating.

## Installation

1. Install/update FjordVPN on the same Docker host.
2. Install FjordSeed from the catalog. Choose app/download directories with Hub's storage picker and UID/GID that can write the downloads.
3. Choose a dedicated Proton NAT-PMP profile with **TCP forwarding disabled**, or an existing shared VPN gateway. Update both apps to use shared gateways.
4. Open Seed, select the profile and Start seedbox.
5. Once VPN readiness is confirmed, add magnets or `.torrent` files.

Managed installations require Hub login and administrator privileges. First-login email/password setup works in the app; membership is rechecked during existing sessions. A centrally required email update appears immediately on opening/returning, without requiring a fresh login. Saving a valid, unique address clears the requirement across updated apps. Update Hub and Seed together.

Standalone: copy `.env.example` to `.env`, set absolute paths and run `docker compose up -d --build`. Read the random first password from `DATA_DIR/initial-login.txt`, username `admin`, and open `http://SERVER-IP:8099`. FjordVPN must still run on the same Docker host.

## Network and runtime

- qBittorrent uses only `network_mode: container:<selected-vpn-id>`, without its own bridge, host network, public WebUI port or Docker socket.
- Gluetun provides the kill switch. The client binds to `tun0`, disables UPnP and uses Gluetun's resolver at `127.0.0.1` inside the namespace.
- Fresh VPN status, an active tunnel, health checks and an assigned Proton port are required before the client starts. VPN failure stops it.
- Assigned ports update through the local API; profile changes/restarts recreate the worker in the correct namespace, retaining torrents.
- One qBittorrent instance per selected VPN profile. Shared gateways can also serve web/media/Minecraft using a separate torrent port. An ordinary TCP-relay profile remains ineligible.
- Stopping Seed stops its client; stopping VPN blocks torrent traffic. Saved torrents resume when the selected VPN is ready.
- The qBittorrent API listens only on loopback. Seed allows specific Docker-exec operations, not a general API proxy.

The panel shows at most 500 torrents. Cached status remains visible during transient worker outages, with diagnostic error/restart information rather than falsely displaying an empty torrent list. Conservative VPN readiness still controls actual traffic. Transient port-renewal timeouts may retry within the already confirmed lease; failed/expired readiness does not fall back to direct internet.

## Shared gateway or dedicated seedbox VPN

Update VPN first, then Seed. Select **Gateway · shared VPN, separate torrent port** and save. The same torrent state/files are reused after a brief client restart; dedicated seedbox profiles remain selectable.

The first gateway port continues HTTPS/Minecraft. Seed reserves another NAT-PMP TCP/UDP mapping using private port 56789, or 56790 if it collides with the first mapping. The public port is announced separately to trackers and displayed in the UI. Renewal runs every 20 seconds. VPN/renewal failure stops the client; changing public ports restarts correct announcement and saved transfers.

Traffic remains on tun0 behind Gluetun, without a torrent proxy, extra VPN configuration or open LAN ports. Existing speed settings remain; shared services naturally share capacity. Stop/profile switch removes only Seed's tagged rules/mapping. If unreachable during cleanup, the lease expires within 60 seconds; web/Minecraft and other profiles remain.

Proton must permit the extra non-symmetric mapping. If it cannot be obtained, qBittorrent stays blocked. See [Gluetun port forwarding](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/port-forwarding.md).

## Storage and completed files

Storage and folders selects an existing writable directory on the Docker host. Hub administrators also see available LXC paths under Proxmox disks/storage; attach missing or read-only storage correctly first. Standalone has a folder picker without Proxmox inventory. Seed does not recursively change shared-directory ownership.

New manual/RSS transfers begin in `.fjordseed-buffer/<id>`. Completed **keep files** torrents move into a unique destination directory, under an RSS subfolder if selected; qBittorrent performs the move and continues seeding there. **Delete files** torrents remain buffered until their automatic seeding condition can safely finish. Move errors are shown; existing releases are not overwritten.

New location choices affect future torrents. Older paths remain mounted for existing transfers, and saving restarts the worker briefly. Back up every `settings.json` storage location. Update Hub, Seed and Flix together: Flix skips the active buffer when scanning. Add the completed directory as a Flix library source and scan retained films.

## Manual downloads and removal

Adding a magnet/file opens source selection followed by Seeding and files. File action comes first. **Keep files** means unlimited seeding until manual stop; automatic ratio/time deletion is inactive. **Delete files** requires explicit selection and uses a minimum credited target ratio of 1 or 49 hours of active seeding (48 hours plus a one-hour safety buffer).

Before automatic removal, the worker waits until no connected downloaders need data and upload is zero. Unknown peer status delays the action. This uses connected qBittorrent `num_leechs`, not tracker-wide swarm totals. Native qBittorrent stop limits are disabled so they do not cut downloaders off between checks. Worker checks run roughly every ten seconds without an open browser and survive restarts. Control errors retain seeding; VPN protection remains active.

Pause/start is a combined control, and paused time does not advance Seed's active seeding clock. Ratio-only temporary downloads can use credited ratio without elapsed-time completion. Editing Ratio changes a torrent's goal/file action without restarting or lifting a manual pause. An already met deletion goal is highlighted before saving. Calls omitting file action preserve the stored choice.

Manual stop/removal remains available with confirmation. If credited ratio is below 1 and active seeding is below 49 hours, an early-stop warning shows current figures regardless of a custom automatic target. The server rechecks on execution.

**Remove opens a confirmation modal with two distinct choices: remove only the torrent and retain downloaded files, or remove the torrent and downloaded files.** Retained files are not deleted merely because the torrent disappears from the list. Automatic deletion follows the stored file action, rather than this manual choice. Review early-stop warnings before confirming.

## Tracker accounts, benefits and covers

Add a NordicBytes account with a read-capable API key. Cards show account upload/download/ratio/buffer/seeding/bonus/warnings separately from local qBittorrent statistics. Refresh runs at most every five minutes and after configuration changes. Outages retain the last sample with timestamp/error. Keys are stored in `DATA_DIR/trackers.json`, mode 0600, never returned to the UI/worker. Blank key edits preserve the key; removing an account keeps torrents/files. Other providers need their own integration.

Exact info-hash matches determine benefits; torrent announce URLs are never called for metadata lookup. Searches are bounded to 50 results/page and three pages per name variant, cached five minutes. V1, pure v2 SHA-256 and hybrid hashes are supported. Featured entries are interpreted as 100% freeleech/double upload according to the [NordicBytes definition](https://github.com/Prowlarr/Indexers/blob/master/definitions/v11/nordicbytes.yml). Unknown benefits do not block ordinary downloads; configured RSS badge requirements do.

NordicBytes global freeleech is also checked through the account API's typed
`global_freeleech` events. Fresh account data (refreshed every minute, accepted
for at most two minutes) and a valid future expiry are required. The preview
shows a Global freeleech badge and local expiry time, and uses 100% freeleech
in its ratio estimate while active. This does not grant double upload. The
torrent's own discount is retained underneath; global events are re-evaluated
even for cached lookups and saved torrent cards, and are never frozen into
saved benefits. RSS freeleech filters also recheck expiry before starting.
Failed/stale account reads do not grant a global discount. The estimate applies
to the current event window; downloads continuing after it expires can count
toward account download again.

Manual additions can estimate account ratio after a full download: `upload / (recorded download + torrent size × (1 − freeleech / 100))`. File size comes from torrent metadata or an exact tracker match. Full freeleech adds no download charge; unknown freeleech is treated conservatively as ordinary download. Account data must be at most ten minutes old. A chosen account can be used with file size when benefits are unknown. Estimated ratio ≤ 0.5 warns without blocking. Future uploads/other downloads/benefit changes are excluded; double upload only contributes when uploaded. This is distinct from the per-torrent seeding goal.

Manual and RSS cards use NordicBytes `meta.poster` from an exact hash match, with no separate title service/key. Existing torrents get asynchronous cover lookup without changing seeding state. Allowed images are fetched without tracker credentials and served locally to authenticated users. The temporary `DATA_DIR/cover-cache` is limited to 64 MiB, 2 MiB/image, 24-hour refresh and seven-day cleanup; failures keep normal cards/downloads.

## RSS feeds and shared download queue

Manual downloads and RSS have separate views but share one native queue with **eight active downloads total**. Seeding, manual pauses and errors take no download slot. The worker prioritizes RSS before manual transfers, maintaining order within each group and leaving manually paused entries paused. Queue reconciliation runs about every ten seconds; RSS arrivals can push manual transfers back into waiting.

Create/edit a feed in the modal. Set a subfolder (empty uses root), seeding/file rules and a fixed start time: now, 1/3/7 days ago, custom date/time or all feed entries. New feeds start paused; each card has an independent on/off switch. The inclusive UTC timestamp is shown in local browser time and does not shift on restart/edit. The feed must still publish those entries; no hidden tracker archive is downloaded. Removing a feed keeps its existing torrents/files and their RSS origin. Setting changes affect new transfers.

qBittorrent fetches feed URLs through the VPN; the administration container does not fetch them. Native auto-download rules remain off so Seed enforces shared seeding rules and readiness before starting. Secret URLs/passkeys stay in 0600 files and are not returned to the browser; a blank URL edit preserves the old one.

### Title filters and required badges

Each feed also has an optional **maximum total torrent size**, entered in MB, GB or TB (binary units: 1 GB = 1024 MB). Leave it empty for no limit. The exact byte limit persists across restarts and can be changed/cleared when editing a feed. The VPN worker checks torrent metadata before adding content and rechecks immediately before download; equality with the limit is allowed. Oversized torrents and unknown sizes, including magnets without confirmed total size, are skipped/retried rather than bypassing the cap. Existing downloads are unaffected. This limits each complete torrent, not the cumulative feed size or available disk capacity.

Title filter has **Look for** and **Avoid** lists of plain fragments, not regexes. Any include matches unless that list is empty; exclusions always win. Matching normalizes case, punctuation, underscores, hyphens and spaces. Each list permits 50 fragments of 120 characters. Drag across lists, or select and Move/Remove selected for keyboard/mobile use. Apply transfers changes to the feed form; Save feed persists them. Filters run before metadata lookup and again before download. Missing titles are skipped when filters are configured; existing transfers are unaffected.

Size/leecher filters belong in the tracker's RSS link. Seed's optional required badges are conjunctive: all selected badges must be confirmed on the same exact hash with a fresh account lookup. 100% Freeleech requires exactly 100%; Double upload, Featured, Internal and Refundable require confirmed flags. Unknown/error/stale responses do not start a badge-gated download. NordicBytes badge gating requires active API access and survives outages. With no badges, no badge restriction applies.

Date filtering occurs before metadata retrieval. Entries without usable dates are skipped when a start date is set; all entries requires none. qBittorrent may substitute malformed RSS dates, so providers should publish proper dates. RSS does not itself require a tracker API key. History/pending metadata under `DATA_DIR/qbit/rss-*` must be backed up. Ambiguous add failures record the attempt to prevent duplicate downloads; inspect the client before repeating manually.

### Persistent feed history and credited upload

Feed cards show **Total credited upload** with the same Green accounting as torrent ratios. Under feed details, **Downloaded titles** lists started titles and their credited upload, including unfinished downloads. The ledger/title history persists in `DATA_DIR/qbit/green-credit.json` after torrent/file deletion or feed pause. Repeated status samples do not count bytes twice, and re-downloading the same torrent collects credit under the same title.

Existing visible torrents register on the next accounting pass. Already deleted entries without saved titles/counters cannot be recovered. Unknown Green history is marked conservatively. These figures are app calculations, not a verified tracker statement; Awaiting upload figures appears until the ledger is readable.

## Green upload accounting

An exact NordicBytes match uses the timezone-aware tracker `created_at`, not the local addition date. The conservative Green period is 24 hours plus 30 minutes. Upload during it receives half credit, later upload full credit: `credited upload = total uploaded − Green upload / 2`. A target of 1 needs local ratio 2 if all upload falls in that period. Expiry never retroactively doubles old credit. Verified own uploads are exempt; anonymous ownership stays conservative.

The worker samples at least every ten seconds; an interval crossing expiry is fully half-credited. The atomic, process-locked ledger in `DATA_DIR/qbit/green-credit.json` retains targets/credits and must be backed up. Historic bytes cannot be precisely apportioned for older torrents; possible Green bytes are conservatively estimated. Torrents added after the period receive full credit.

Date checks also run for RSS without a browser. During pending verified-date lookup, targets are conservatively doubled. Without an API account, Green cannot be established and ordinary ratio applies. With an account but no provable date, the conservative doubled target remains marked. Unknown lookups retry after the five-minute cache; verified findings remain frozen. This governs the per-torrent credited target, not account-wide ratio or other bonus multipliers. The buffer does not extend the tracker's real freeleech period.

## Chrome extension

The Manifest V3 [extension](chrome-extension/README.md) sends NordicBytes torrent/RSS links into an existing Seed tab. Torrent links open the normal manual dialog; RSS opens the feed form with its full address. Users confirm settings before starting/saving. Private parameters are handed off through extension session storage, never a destination URL, and RSS is not fetched by the extension.

Package with `python tools/package_chrome_extension.py`; the ZIP is served at `/static/fjordseed-chrome.zip`. Extension tests: `node --test tests/test_chrome_extension.mjs` and `python tests/browser_extension_check.py`.

## Operations and tests

Back up `DATA_DIR`, every storage/download location, qBittorrent state, RSS metadata and the credit ledger. `docker compose down --remove-orphans` removes runtime while preserving bind mounts. Stop Seed before rollback. Updates briefly interrupt VPN-bound transfers, then resume saved state. Shared directories need appropriate permissions; existing ownership is not changed recursively.

The Docker socket makes this host-administration software; use trusted access/HTTPS. Seed has no direct Proxmox key and receives only filtered VPN profiles/status, not private VPN keys.

```sh
python -m pytest tests -q
python tests/browser_check.py
```

`tests/container_check.py` runs in the app image with `--network none` and exercises real client configuration/readiness without downloads. A live Proton end-to-end test needs a dedicated test profile: verify exit IP, perform a permitted test transfer and verify stopping VPN stops traffic. Isolated fixtures are not proof of every real tunnel.

References: [Gluetun container networking](https://github.com/qdm12/gluetun-wiki/blob/main/setup/connect-a-container-to-gluetun.md), [qBittorrent Web API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29).


### FjordHub Matrix notifications and daily downloads

When managed by FjordHub, the existing torrent status poll reports actual
transitions to active downloading for RSS-tagged torrents, including the file
name and RSS feed name. A start push is sent only once per torrent, not whenever
the application is refreshed or restarted. Completion of RSS or manually added
torrents is also recorded in FjordHub, allowing the Matrix bot to answer
questions such as "Er der downloadet noget nyt i dag?" without pushing a
notification for every completion. Previously existing torrents are
baselined on the first healthy poll to prevent an alert storm.

The `event_notifier.py` durable queue survives restarts, deduplicates
events, and retries when FjordHub is unavailable. Only the existing managed
`FJORDHUB_URL`/`FJORDHUB_API_KEY` credentials are used. Update FjordHub
before FjordSeed.

### Torrent pages and bot status

Manual and RSS download lists each show five torrents per page, with independent Previous/Next controls. Counts and transfer rates cover the entire list. The selected page survives status refreshes and clamps when torrents are removed.

The FjordHub Matrix bot can read a dedicated live torrent summary using the existing app key at `GET /api/hub/bot/seeding`. Browser login alone does not grant this access. Only titles, transfer state, progress and seeding goal metrics are exposed; tracker URLs, paths and credentials are excluded. Both applications and the bot must be updated.

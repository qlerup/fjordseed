# FjordSeed

The standalone Windows GPU converter is in
[`desktop-converter/`](desktop-converter/README.md), including the desktop UI,
drag-and-drop support and an installer for its NVEncC toolchain.

Conversion can also run on a paired Windows PC: see
[PC conversion and device tokens](docs/pc-conversion.md). Conversion settings
and PC pairing share **Indstillinger → Konvertering**. This mode needs no
server GPU and remains disabled until explicitly enabled.

A separate FjordHub seedbox with bundled qBittorrent. FjordVPN manages Proton profiles; installation starts no torrents. The interface currently uses Danish labels.

## Optional GPU conversion before library publication

During installation, enable **Installer NVIDIA GPU-konvertering** in FjordHub's
GPU step. It uses the same GPU helper, preflight, NVIDIA Container Toolkit and
discovered device mappings as FjordLens/FjordFlix. The optional Compose file
builds a checksum-pinned NVEncC 9.39 toolchain, FFmpeg and MKVToolNix. FjordHub
tests both NVENC and an actual NVEncC HEVC encode. No separate HandBrake Lab
installation, fixed IP address or Proxmox container ID is required.

In Seed, enable conversion under **Indstillinger → Konvertering**, choose a video
bitrate (30 Mbps by default; 20 Mbps saves space, 30 Mbps balances size and quality,
and 40 Mbps prioritizes quality), then opt in on individual manual downloads or RSS
feeds. Feed edits affect future downloads only. Disabling the main switch stops
new converted additions; already accepted jobs finish. Conversion-enabled feeds
wait for re-enablement or for their conversion option to be cleared, rather than
silently downloading/publishing originals. Existing unselected torrents retain
their policies. GPU installation alone never enables conversion on existing feeds.

The pipeline is download to `.incomplete`, convert to a separate MKV, validate,
then atomically publish only the converted directory to the captured destination.
The qBittorrent original never moves. Its automatic removal requires **both** a
published conversion **and** real 1:1 upload/download ratio **or** 49 hours of
active seeding. This conversion policy replaces the ordinary retention policy
for selected downloads; unlike ordinary cleanup, it does not wait for peers
after the threshold. Errors or insufficient space retain the source. The UI shows
queue/encode/verification/error state; failed jobs can be retried under details.

NVENC encodes HEVC with software decoding (`--avsw`) and preserves resolution,
frame rate, audio/subtitle codecs and language, default/forced flags, chapters
and supported HDR metadata. Dolby Vision profile 7 becomes profile 8.1 with
HDR10; its enhancement layer is not preserved. Unsupported DV profiles fail
closed. Bitrate is an average video target (1.5× peak); audio adds to total
bitrate. Lossy conversion can reduce picture detail. Selected non-video sidecars
are copied, and all selected videos in a multi-file torrent must pass before
the directory is published. A conservative source-size + 1 GiB free-space
reserve is required; source, output and temporary work share the buffer disk.

The idle `converter` Compose service supplies the tested image/GPU configuration.
Seed creates one bounded queue worker with those NVIDIA devices, 4 CPU cores,
6 GiB memory, no network, no Docker socket, a read-only root and writable mounts
of **only the known `.incomplete` directories**. qBittorrent remains GPU-free
inside its original VPN network. Storage changes recreate only the converter
worker as needed; verified per-file results survive restarts. Per-job file locks
prevent duplicate encoding when buffers are shared. GPU capacity is shared with
Plex/Flix/Lens; one conversion runs at a time per queue worker.

Keep `download-storage.json`, the normal app-data backup and buffer contents
together. Requests, progress and `encoder.log` live in each download's hidden
`.fjordseed-conversion` directory. Do not roll back to a release without conversion
support while converted torrents remain: that release does not understand their
source-retention guard. Disable new conversions, drain the queue and wait for
original cleanup first, or stop the seedbox and back up its data before rollback.
The library copies remain independent after original torrents are removed.

Standalone installation: include `docker-compose.gpu.yml` after the base Compose
file, supply the host's actual NVIDIA device mappings and use a working NVIDIA
Container Toolkit. FjordHub generates these overrides automatically. Enabling
GPU on an existing non-GPU install requires applying the GPU installation option,
not merely changing the switch inside Seed. Source updates are published to GitHub;
the user applies the app update through FjordHub.

## Account and traffic charts

The account overview includes a five-view chart carousel: account ratio,
credited upload, physical upload, credited download and physical download.
Ratio and credit come from the selected tracker's account API and include the
whole account. Physical counters come from qBittorrent's `alltime_ul` and
`alltime_dl` statistics and include the whole seedbox, across trackers. The UI
labels these sources separately; physical traffic is not assigned to the
selected tracker. The counters are read through the existing VPN-only RPC.

Samples are collected in the background every ten minutes and retained for
30 days in `/data/tracker-history.sqlite3`, independently of the open browser.
History starts when this version is installed. Missing values are not recorded
as zero, outages create chart gaps, and physical counter resets are marked
instead of presented as negative traffic. Display downsampling preserves ratio
extrema and data gaps. Existing torrent/seeding and credit accounting are
unchanged. Keep the history database with the existing data-directory backup.

The period can be 24 hours, 7 days or 30 days. Automatic quarter-turn cube
transitions run every eight seconds and pause on mouse hover, keyboard use,
hidden tabs or when the chart is off screen. Reduced-motion mode uses manual
selection without rotation. Installing via FjordHub is the user's action;
pushing source changes does not require manually modifying the deployed repo.

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

### Streaming and FjordFlix

The **Streaming** menu controls storage for new manual and RSS downloads.
**Jeg bruger FjordFlix** preserves the existing buffer-and-publish workflow.
Turn it off to download directly into each torrent's final directory, without
a buffer or subsequent move. A small publishing marker keeps unfinished files
out of a Flix library if that directory is indexed later. Existing torrents
retain their original destinations and finish using their captured workflow.
Existing installations keep buffering enabled until explicitly changed.

**Find FjordFlix** reads the existing indexed library folders from the updated
FjordFlix app on the same Docker host. Choose one and connect: Seed translates
the existing Flix bind mount to its host directory, validates write access as
the torrent UID/GID, and mounts that exact directory for new downloads. This
enables streaming; retained completed downloads appear in Flix's normal scans.
Flix's mounts and library sources stay unchanged. A different Seed directory
briefly recreates the torrent worker, retaining all previous torrent mounts.
Both apps must be updated; this link requires a managed Flix installation with
its FjordHub app credential configured. No credential is sent to the browser.
Switching streaming off retains existing library sources and files.

Storage and folders selects an existing writable directory on the Docker host. Hub administrators also see available LXC paths under Proxmox disks/storage; attach missing or read-only storage correctly first. Standalone has a folder picker without Proxmox inventory. Seed does not recursively change shared-directory ownership.

While **Jeg bruger FjordFlix** is enabled, Storage and folders shows that
FjordFlix manages storage and disables both folder selection and Proxmox storage
choices. Manual storage changes are also rejected by the API. Connect or change
the shared library under Streaming, or disable FjordFlix to select storage manually.

With buffering enabled, new manual/RSS transfers begin in `.incomplete/<torrent-name>` (a short ID is added on name conflicts). Existing torrents keep their stored paths, including the previous `.fjordseed-buffer` folder. FjordFlix excludes both buffer folder names. Completed **keep files** torrents move into a unique destination directory, under an RSS subfolder if selected; qBittorrent performs the move and continues seeding there. **Delete files** torrents remain buffered until their automatic seeding condition can safely finish. Move errors are shown; existing releases are not overwritten. With buffering disabled, both file actions download directly into unique final directories instead. FjordFlix mode always requires buffering.

New location choices affect future torrents. Older paths remain mounted for existing transfers, and saving restarts the worker briefly. Back up every `settings.json` storage location. Update Hub, Seed and Flix together: Flix skips the active buffer when scanning. Add the completed directory as a Flix library source and scan retained films.

## Manual downloads and removal

The explicit **Automatisk: optimer ratio og slet** choice adds an adaptive upload
forecast to manual downloads, RSS feeds and existing torrent edits. Standard
ratio/49-hour deletion, ratio-only deletion and existing torrents keep their
previous behavior; the adaptive policy is opt-in and uses ratio/49-hour goals.
Its minimum ratio defaults to 1:1 and can be raised. It retains
the user's original goals and extra-time preference. After a goal
is reached, the worker keeps seeding while the forecast is worthwhile, in addition
to the existing protection for connected downloaders and actual ongoing upload.
It never starts paused torrents or changes the behavior of **keep files**.

The forecast uses measured physical upload-counter growth with an exponential
10-minute smoothing time constant, after at least two minutes of observations.
Let `r` be the smoothed actual uploaded bytes/second, `D` the downloaded bytes used for
the physical torrent ratio, `L` the swarm's downloaders and `S` its seeders. When swarm counts
are known, the next 30 minutes' forecast is
`E = min(r * 1800 * min(1, L / (S + 1)), D * L / (S + 1))`.
With unknown swarm counts it uses measured `r * 1800`; a known zero downloader
count gives zero. Extension requires both `E >= 64 MiB` and `E / D >= 0.05`.
The swarm counts are qBittorrent's documented `num_incomplete`/`num_complete`,
distinct from connected peers (`num_leechs`): see the
[official API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29).

The persisted estimate is shared by status requests and the worker, which
rechecks about every ten seconds without an open browser. It decays with no
traffic, expires after 15 minutes without measured upload, and resets after a
pause, move, counter reset, clock rollback or observation gap longer than two
minutes. Swarm demand or a high lifetime ratio alone cannot trigger extension.
When potential falls, normal deletion resumes once no connected downloader or
upload needs protection. The UI labels automatic extensions and shows estimated
extra physical upload and ratio gain. These are forecasts, not guaranteed upload.

Adding a magnet/file opens source selection followed by Seeding and files. File action comes first. **Keep files** means unlimited seeding until manual stop; automatic ratio/time deletion is inactive. **Delete files** requires explicit selection and uses a minimum physical upload/download target ratio of 1 or 49 hours of active seeding (48 hours plus a one-hour safety buffer).

Before automatic removal, the worker waits until no connected downloaders need data and upload is zero. Unknown peer status delays the action. This uses connected qBittorrent `num_leechs`, not tracker-wide swarm totals. Native qBittorrent stop limits are disabled so they do not cut downloaders off between checks. Worker checks run roughly every ten seconds without an open browser and survive restarts. Control errors retain seeding; VPN protection remains active.

Pause/start is a combined control, and paused time does not advance Seed's active seeding clock. Ratio-only temporary downloads use physical upload/download ratio without elapsed-time completion. Editing Ratio changes a torrent's goal/file action without restarting or lifting a manual pause. An already met deletion goal is highlighted before saving. Calls omitting file action preserve the stored choice.

Manual stop/removal remains available with confirmation. If physical torrent ratio is below 1 and active seeding is below 49 hours, an early-stop warning shows current figures regardless of a custom automatic target. The server rechecks on execution.

Physical upload/download totals are accumulated in the durable ledger. If qBittorrent restores an older resume checkpoint after a restart, recorded traffic remains in the ratio and future counter growth is added once. Legacy Green byte buckets can recover previously observed upload; tracker account credit is never used to invent physical traffic. Re-adding a torrent with a new addition date starts a new transfer lifetime. Adaptive forecasts reset at a counter rollback so recovered history cannot appear as a burst of new upload. qBittorrent's own resume-save interval is set to one minute when supported.

**Remove always offers three choices:** remove the torrent and its files,
remove only the torrent and retain its files, or delete only the files and
retain the torrent stopped. All three are available regardless of the saved
automatic seeding/file rule. The default retains files until explicitly changed.
Files-only deletion confirms the seeding warning, stops the client torrent,
then deletes only its API-listed files under the mounted download directories.
Links and path traversal are refused. The torrent/accounting history remains;
the UI shows files deleted and zero completed bytes. Explicit Start rechecks
the files and can download them again. Automatic deletion still follows the
saved seeding rule. Existing payloads are never deleted merely by opening or
cancelling the dialog.

## Tracker accounts, benefits and covers

Add a NordicBytes or Sagmire account with a read-capable API key. Both use the same account/torrent API format and support account statistics, exact-hash benefits, covers, global freeleech, Green accounting and RSS badge requirements. Provider destinations are fixed; each key is sent only to its own tracker. Cards show account upload/download/ratio/buffer/seeding/bonus/warnings separately from local qBittorrent statistics. Account refresh runs every ten minutes and after configuration changes. Outages retain the last sample with timestamp/error. Keys are stored in `DATA_DIR/trackers.json`, mode 0600, never returned to the UI/worker. Blank key edits preserve the key; removing an account keeps torrents/files. Other providers need their own integration. Sagmire's matching API format is supplied by the operator; authenticated live behavior still requires the user's Sagmire API key.

Exact info-hash matches determine benefits; torrent announce URLs are never called for metadata lookup. Searches are bounded to 50 results/page and three pages per name variant, cached five minutes. V1, pure v2 SHA-256 and hybrid hashes are supported. Featured entries are interpreted as 100% freeleech/double upload according to the [NordicBytes definition](https://github.com/Prowlarr/Indexers/blob/master/definitions/v11/nordicbytes.yml). Unknown benefits do not block ordinary downloads; configured RSS badge requirements do.

NordicBytes and Sagmire global freeleech is also checked through the account API's typed
`global_freeleech` events. Fresh account data (refreshed every ten minutes, accepted
for at most ten minutes) and a valid future expiry are required. The preview
shows a Global freeleech badge and local expiry time, and uses 100% freeleech
in its ratio estimate while active. This does not grant double upload. The
torrent's own discount is retained underneath; global events are re-evaluated
even for cached lookups and saved torrent cards, and are never frozen into
saved benefits. RSS freeleech filters also recheck expiry before starting.
Failed/stale account reads do not grant a global discount. The estimate applies
to the current event window; downloads continuing after it expires can count
toward account download again.

Manual additions can estimate account ratio after a full download: `upload / (recorded download + torrent size × (1 − freeleech / 100))`. File size comes from torrent metadata or an exact tracker match. Full freeleech adds no download charge; unknown freeleech is treated conservatively as ordinary download. Account data must be at most ten minutes old. A chosen account can be used with file size when benefits are unknown. Estimated ratio ≤ 0.5 warns without blocking. Future uploads/other downloads/benefit changes are excluded; double upload only contributes when uploaded. This is distinct from the per-torrent seeding goal.

Manual and RSS cards use the selected tracker's `meta.poster` from an exact hash match, with no separate title service/key. Existing torrents get asynchronous cover lookup without changing seeding state. Allowed images are fetched without tracker credentials and served locally to authenticated users. The temporary `DATA_DIR/cover-cache` is limited to 64 MiB, 2 MiB/image, 24-hour refresh and seven-day cleanup; failures keep normal cards/downloads.

Existing torrents can fetch tracker details and a missing poster after being
added: open **Vis detaljer → Hent trackerdata igen**. This queues a fresh
exact-hash lookup immediately, including after a cached API failure. Repeated
clicks share the pending lookup. Downloads and seeding keep running; verified
Green/accounting data is preserved while missing display data is enriched.

Missing tracker details, an unknown Green date, unknown freeleech/double-upload
flags or a missing poster trigger up to **three additional automatic lookups**,
with **two minutes between completed attempts**. The existing background worker
does this without an open browser. Retry counts and deadlines survive app
restarts. A complete result ends retries; after three unsuccessful retries,
the manual button can start a new series. Newly verified Green dates are
published to the running worker's accounting policy, while already verified
dates and seeding goals are preserved. Until a date is known, conservative
Green accounting continues; an API failure never invents freeleech or stops
an existing transfer.

## RSS feeds and shared download queue

Manual downloads and RSS have separate views but share one native queue with **eight active downloads total**. Seeding, manual pauses and errors take no download slot. The worker prioritizes RSS before manual transfers, maintaining order within each group and leaving manually paused entries paused. Queue reconciliation runs about every ten seconds; RSS arrivals can push manual transfers back into waiting.

Create/edit a feed in the modal. Set a subfolder (empty uses root), seeding/file rules and a fixed start time: now, 1/3/7 days ago, custom date/time or all feed entries. New feeds start paused; each card has an independent on/off switch. The inclusive UTC timestamp is shown in local browser time and does not shift on restart/edit. The feed must still publish those entries; no hidden tracker archive is downloaded. Removing a feed keeps its existing torrents/files and their RSS origin. Setting changes affect new transfers.

qBittorrent fetches feed URLs through the VPN; the administration container does not fetch them. Native auto-download rules remain off so Seed enforces shared seeding rules and readiness before starting. Secret URLs/passkeys stay in 0600 files and are not returned to the browser; a blank URL edit preserves the old one.

### Title filters and required badges

Each feed also has an optional **maximum total torrent size**, entered in MB, GB or TB (binary units: 1 GB = 1024 MB). Leave it empty for no limit. The exact byte limit persists across restarts and can be changed/cleared when editing a feed. The VPN worker checks torrent metadata before adding content and rechecks immediately before download; equality with the limit is allowed. Oversized torrents and unknown sizes, including magnets without confirmed total size, are skipped/retried rather than bypassing the cap. Existing downloads are unaffected. This limits each complete torrent, not the cumulative feed size or available disk capacity.

Title filter has **Look for** and **Avoid** lists of plain fragments, not regexes. Any include matches unless that list is empty; exclusions always win. Matching normalizes case, punctuation, underscores, hyphens and spaces. Each list permits 50 fragments of 120 characters. Drag across lists, or select and Move/Remove selected for keyboard/mobile use. Apply transfers changes to the feed form; Save feed persists them. Filters run before metadata lookup and again before download. Missing titles are skipped when filters are configured; existing transfers are unaffected.

Size/leecher filters belong in the tracker's RSS link. Seed's optional required badges are conjunctive: all selected badges must be confirmed on the same exact hash with a fresh account lookup. 100% Freeleech requires exactly 100%; Double upload, Featured, Internal and Refundable require confirmed flags. Unknown/error/stale responses do not start a badge-gated download. NordicBytes and Sagmire badge gating requires active API access and survives outages. With no badges, no badge restriction applies.

Date filtering occurs before metadata retrieval. Entries without usable dates are skipped when a start date is set; all entries requires none. qBittorrent may substitute malformed RSS dates, so providers should publish proper dates. RSS does not itself require a tracker API key. History/pending metadata under `DATA_DIR/qbit/rss-*` must be backed up. Ambiguous add failures record the attempt to prevent duplicate downloads; inspect the client before repeating manually.

### Persistent feed history and credited upload

Feed cards show **Total credited upload** as an estimate of tracker account credit, separate from physical torrent ratios. Under feed details, **Downloaded titles** lists started titles and their credited upload, including unfinished downloads. The ledger/title history persists in `DATA_DIR/qbit/green-credit.json` after torrent/file deletion or feed pause. Repeated status samples do not count bytes twice, and re-downloading the same torrent collects credit under the same title.

Existing visible torrents register on the next accounting pass. Already deleted entries without saved titles/counters cannot be recovered. Unknown Green history is marked conservatively. These figures are app calculations, not a verified tracker statement; Awaiting upload figures appears until the ledger is readable.

## Green upload accounting

An exact NordicBytes or Sagmire match uses the timezone-aware tracker `created_at`, not the local addition date. The conservative Green period is 24 hours plus 30 minutes. Upload during it receives half credit, later upload full credit: `credited upload = total uploaded − Green upload / 2`. Torrent seeding goals always use actual upload/download: a target of 1 needs physical ratio 1, including during Green. Expiry never retroactively doubles old credit. Verified own uploads are exempt; anonymous ownership stays conservative.

The worker samples at least every ten seconds; an interval crossing expiry is fully half-credited. The atomic, process-locked ledger in `DATA_DIR/qbit/green-credit.json` retains targets/credits and must be backed up. Historic bytes cannot be precisely apportioned for older torrents; possible Green bytes are conservatively estimated. Torrents added after the period receive full credit.

Date checks also run for RSS without a browser, solely to estimate account credit. Green, pending or unavailable metadata, freeleech and other account multipliers never change per-torrent targets, early-stop warnings, seeding completion or adaptive upload forecasts. Existing saved goals and seed clocks are preserved. Old credit-based adaptive forecasts are discarded once and retrained from physical upload counters. The Green buffer does not extend the tracker's real freeleech period.

## Chrome extension

The Manifest V3 [extension](chrome-extension/README.md) sends NordicBytes/Sagmire torrent/RSS links into an existing Seed tab. Torrent links open the normal manual dialog; RSS opens the feed form with its full address. Users confirm settings before starting/saving. Private parameters are handed off through extension session storage, never a destination URL, and RSS is not fetched by the extension.

Package with `python tools/package_chrome_extension.py`; the ZIP is served at `/static/fjordseed-chrome.zip`. Extension tests: `node --test tests/test_chrome_extension.mjs` and `python tests/browser_extension_check.py`.

Downloads now combines manual torrents and RSS in one workspace, with All, Manual and RSS filters. The summary follows the selected filter; the shared queue always shows all downloads. Add opens one source picker for magnet links, torrent files and RSS, retaining separate seeding and feed settings. Existing `#rss` links open the RSS filter. Feed management and history remain available through Manage feeds. RSS configuration remains available while the VPN is offline; manual download submission still requires a ready connection. The overview retains live rates and VPN animation without the small rate-history graphs.

Reload/install Chrome extension 1.2.1 for RSS handoff to the unified dialog (the updated extension also supports the previous UI). UI regression coverage: `python tests/browser_downloads.py`, `python tests/browser_rss_toggle.py`, `python tests/browser_rss_date.py`, `python tests/browser_rss_filters.py`, and `python tests/browser_transfer_flow.py`.

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

### Grouped RSS history

Click a feed name to open its archived downloads, grouped by the series stem in
the original torrent title. Expand a series and a release to inspect physical
upload/download and calculated credit. Unknown historical measurements remain
unknown. Download credit is accumulated only while recently verified freeleech
metadata is available; missing intervals are never filled using today's badge.
Existing Green upload credit is retained without recalculation.

The per-series **Udeluk** action adds the original release's series stem to that
feed's existing exclusion filter. It does not use the custom feed label and does
not stop or delete existing downloads.

Administrator history links can include old feeds using persistent source IDs. Removing an
old feed leaves its archive intact. Source links are direct (not recursive), and
the overview counts each source's credit once. Administrators can provision a
planned replacement feed before removing its predecessors with a private data
file `rss-history-presets.json`, for example
`[{"name":"Dansk TV","sources":["<old feed ID>"]}]`. A matching new feed inherits
those sources even after their configuration was removed. Existing feeds from
older versions with no history-source field are upgraded on startup. No RSS URL,
tracker credential or downloading rule is copied by this history linkage.

For permanent replacement, `tools/rss_history_migration.py` transfers archive
ownership and the live ledger's feed association while writers are stopped.
The operation is idempotent; original archives are retained for recovery. Clear
the destination's source links afterwards to avoid counting copied history twice.
The user history modal requires no feed-selection checkboxes.

RSS tracker credit uses fresh exact-hash API results in a separate accounting
stream. Physical traffic samples are retained with each archived torrent,
including after removal. New upload combines the first **24 hours** of Green
(×0.5) and verified double upload (×2). Downloads use verified freeleech and
current global freeleech expiry. The conservative seeding-goal policy remains
separate from this account-credit estimate and never replaces physical traffic.
Active torrents refresh accounting metadata on a five-minute cache; old display
snapshots do not freeze the accounting flags. Pending API lookups retain ten
minutes of traffic samples, surviving restart/deletion. Backfilled short windows
and samples crossing a timed boundary are marked estimated. Older unclassified
traffic remains unknown; today's badges never rewrite the saved legacy total.

### Torrent pages and bot status

Manual and RSS download lists each show five torrents per page, with independent Previous/Next controls. Counts and transfer rates cover the entire list. The selected page survives status refreshes and clamps when torrents are removed.

The FjordHub Matrix bot can read a dedicated live torrent summary using the existing app key at `GET /api/hub/bot/seeding`. Browser login alone does not grant this access. Only titles, transfer state, progress and seeding goal metrics are exposed; tracker URLs, paths and credentials are excluded. Both applications and the bot must be updated.

Temporary storage accounting: the feed manager shows allocated bytes across all known download buffers, including manual downloads and temporary seeding. Storage and Streaming highlight the RSS subset in blue within used space, restricted to the selected filesystem. RSS membership comes from the persisted credit history and captured torrent stage paths. Both `.incomplete` and legacy `.fjordseed-buffer` are scanned read-only, without following symbolic links; hardlinked files are counted once and sparse files use allocated blocks. Measurements are cached for 30 seconds, and unavailable classification is shown as unknown rather than zero.

## Existing retained movies

The conversion tab can list existing movies in Behold and send a selected video
to the paired PC. After validation, qBittorrent moves the original torrent into
the hidden seeding folder before the converted movie is published. Keep policies
remain unchanged. Converted movies receive a persistent bitrate/date badge.
See [retained-library conversion](docs/library-conversion.md).

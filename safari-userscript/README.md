# FjordSeed in Safari with Userscripts

This version uses the existing [Userscripts Safari extension](https://apps.apple.com/dk/app/userscripts/id1463298887).
FjordSeed does not publish an iPhone app or require an Apple Developer account.
Userscripts is installed once; the FjordSeed script is then installed from the
user's own FjordSeed server.

**Beta:** the source has not been tested on a physical iPhone. Automated checks
cover code and isolated DOM behavior, not Safari's real touch callout, website
permissions or device lifecycle.

## Installation on an iPhone

1. Open FjordSeed in **Safari on the iPhone** and choose **Opsæt
   Safari-udvidelse**. The setup entry is intentionally hidden in other browsers
   and standalone home-screen web apps.
2. Install Userscripts using the guide's link, open it once, and enable it in
   Safari's extension settings. Allow it on the trackers you use and on your
   FjordSeed site.
3. In the FjordSeed guide, open **Installér FjordSeed i Userscripts**. The address
   ends in `.user.js`. Open Userscripts from Safari's extension menu and choose
   its installation action. The script is already configured with this server's
   exact origin; no password or API key is embedded.
4. Return to FjordSeed and reload it, then open NordicBytes or Sagmire in Safari
   and sign in normally.

The setup code comes from FjordSeed. Torrent metadata comes from the tracker.
These are separate steps; the phone does not download the torrent's payload.

## Choosing the correct torrent

The small FjordSeed tab appears only on supported tracker pages with recognized
download or RSS links. Tap it to see the available links. Holding a supported
download link opens the menu for that exact link, including when an icon or
other element is inside the link.

The menu uses the link's label or a nearby details link for the same torrent ID.
If no useful title is available, it shows the tracker and torrent ID. It never
selects the first torrent on the page on the user's behalf. Moving more than
10 pixels, scrolling, or cancelling the touch cancels the hold gesture. A normal
tap retains the website's normal action.

This is an in-page menu. Apple's native Safari long-press menu is not extended.
JavaScript-only download buttons without a supported link need a separate
tracker integration; they are not guessed from unrelated page content.

## Sending and packages

- **Send til FjordSeed:** for a torrent, fetch its small `.torrent` on the
  tracker page and open FjordSeed to review its normal settings. RSS opens the
  normal feed form. Confirm in FjordSeed before starting or saving.
- **Føj til pakke:** retain the selected torrent in the local handoff queue.
  Select more torrents, then choose **Åbn FjordSeed**. The receiver stages them
  through FjordSeed's existing manual package endpoint. Review the resulting
  package before starting downloads.
- An open dialog is not overwritten. Pending handoffs can wait while the user
  finishes the dialog or signs in. Resume or clear the pending selections in
  FjordSeed when needed.

The script targets NordicBytes and Sagmire torrent download links and RSS feeds,
matching the Chrome extension's existing link rules. It does not add arbitrary
tracker or generic magnet-link support. Opening FjordSeed may open a new Safari
tab; the script does not have the native extension's tab-query/reuse APIs.

## Data handling

Tracker requests are ordinary same-origin fetches using the existing tracker
login. RSS feeds are not fetched by the script. The receiver runs on the exact
configured FjordSeed origin, including its port, and uses the existing website
session and CSRF protection to save package drafts.

Pending handoffs use **persistent local Userscripts storage**, shared across
the pages running the same installed script. They expire after 15 minutes and
are removed on successful delivery or explicit clearing. Expired entries are
cleaned up when the script next runs; closing Safari alone does not erase them.
Private feed addresses and torrent data are not included in navigation URLs,
visible link labels or the installed script file.

The installer is public because Userscripts fetches `.user.js` URLs without
relying on the website's login session. Its only installation-specific value
is the validated server origin. Existing protected application routes remain
protected. Install the script from the FjordSeed server you intend to use.

## Sources and deployment

`safari_setup.py` assembles the installer from:

- `chrome-extension/common.mjs`: shared link validation and FjordSeed handoff
  functions.
- `safari-userscript/panel.js` and `panel.css`: the contextual side tab and touch
  menu.
- `safari-userscript/runtime.js`: the Userscripts transport and receiver.

The Docker image includes these sources. The setup guide supplies the external
origin so HTTPS behind a reverse proxy is preserved. Host validation prevents
the installer parameter from substituting an unrelated destination host.

The script requests only the GM storage and tab-opening APIs it uses, runs in
the isolated content context, and excludes frames. No cross-origin network API
or embedded API key is required.

## First device check

After installation, check a page with several torrents. Hold the second link
and verify its title/ID in the menu, then cancel. Check that swiping the page
does not open the menu. Send one authorized test torrent and one test feed,
confirming that they reach the right FjordSeed forms without starting a download
automatically. Finally, add two torrents to a package, open FjordSeed and review
the draft. Include a login interruption and an already open dialog.

Official platform references:

- [Userscripts installation and API documentation](https://github.com/quoid/userscripts)
- [Userscripts App Store release API](https://github.com/quoid/userscripts/tree/release/4.x.x#api)
- [Safari extension API compatibility](https://developer.apple.com/documentation/safariservices/assessing-your-safari-web-extension-s-browser-compatibility)

## Automated checks

With the repository's Python test dependencies installed:

```sh
python -m pytest -q tests/test_safari_setup.py tests/test_docker_context.py
node --test tests/test_safari_setup.mjs tests/test_chrome_extension.mjs
```

The isolated runtime/DOM checks use Happy DOM. Install it outside the repository,
then provide the path to its module:

```sh
npm install --prefix /tmp/fjordseed-test-dom --no-save happy-dom
FJORDSEED_TEST_HAPPY_DOM=/tmp/fjordseed-test-dom/node_modules/happy-dom/lib/index.js \
  node --test tests/test_safari_userscript.mjs
```

These checks mock GM storage and tracker responses. They do not contact live
trackers or initiate torrent downloads. They also do not substitute for the
device check above.

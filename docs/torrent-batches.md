# Multiple manual torrent files

The Torrentfil tab accepts multiple file-picker selections and drag-and-drop.
Selections accumulate until cleared; individual files can be removed. The browser
accepts up to 50 non-empty `.torrent` files, up to 4 MiB per file. Identical files
are detected by a checksum followed by byte-for-byte comparison (including files
with different names); no browser cryptography or HTTPS-only API is required.
Server validation and request-size limits remain authoritative.

One file keeps the original review flow. Multiple files show a card for each
torrent, with independent tracker selection, Freeleech/other badges, estimated
account ratio and lookup status. Ratio estimates apply to each torrent separately,
not to the combined batch; this is stated in the dialog. Common conversion and
seeding settings, including manual minute deadlines, apply to every submitted
file. RSS and magnet-link behaviour are unchanged.

The browser uses the existing authenticated, CSRF-protected preview and add APIs
once per file. At most three preview requests run concurrently. Pending lookups
are polled with backoff and a finite waiting period. Closing the review or changing
a file's tracker cancels stale requests and prevents late results from overwriting
the current card. Client timeouts do not bypass backend validation or VPN gating.

Adds run sequentially using a snapshot of the chosen settings. Each success stays
marked as added and is omitted from retries and the file picker when going back.
Failures remain visible alongside their files; an uncertain network result asks
the user to check Downloads before retrying. Invalid preview responses cannot be
submitted as part of the batch. Filenames and API text are rendered as text, never
interpolated HTML.

Verification:

```sh
python tests/browser_torrent_batch.py
python tests/browser_manual_seed_minutes.py
python tests/browser_keep_seeding.py
node tests/preview_polling_check.cjs
python -m pytest tests/test_benefits.py tests/test_ratio_preview.py tests/test_manual_seed_minutes.py -q
```

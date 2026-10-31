# Themes and manual seed timers

## Appearance

Settings → Tema offers **Fjord** (the original aurora landscape and interactive
goats) and **Viking** (iron/bronze surfaces, an illustrated fjord and interactive
SVG warriors). Fjord remains the default on existing installations. The theme
and animation preference persist in the existing `settings.json`, independently
of VPN settings. They apply to this FjordSeed instance and are rendered on the
initial HTML response, avoiding a flash of the wrong theme after reload.

The Viking background uses original local vector artwork; it downloads no
third-party graphics, video or scripts. Visual research included
[Art of the Viking Age](https://smarthistory.org/viking-art/) and the
[Viking Ship Museum's rune-stone ships](https://www.vikingeskibsmuseet.dk/en/professions/education/the-longships/picture-sources/the-ships-on-the-rune-stones).
The artwork is a stylised interpretation, not a historical reconstruction.

The battle lasts 300 seconds of visible, unpaused animation time:

- 0–15 seconds: the armies enter from outside the viewport.
- 15–270 seconds: skirmishes and defeats; clicking a warrior swings an axe and
  defeats that warrior. Keyboard activation works too.
- 270–296 seconds: survivors withdraw beyond the viewport edges.
- 296–300 seconds: an empty battlefield before the next army enters.

The scene lives behind application controls, like the goats, with no separate
battle view. Empty page gutters pass clicks to visible actors; controls and
panels retain priority. The renderer stops when Viking is not selected, the tab
is hidden, a dialog is open, or animation is disabled. System reduced-motion
preferences produce a still, interactive scene. Mobile starts with fewer actors.

## Manual seed deadline

The manual torrent/magnet flow includes **Seed i X min · slet bagefter**. It
accepts 1–525600 whole minutes, with a suggested value of 60. This option is absent
from RSS forms and rejected by RSS validation. Existing minute-based downloads
can have their duration edited; the mode cannot be enabled on existing RSS
downloads. Selecting a different policy clears the custom deadline.

`delete_time` persists `seed_minutes` in the credit ledger before qBittorrent
starts. It uses the existing verified active seed clock, including its restart,
pause and VPN/network-health handling. A high ratio never ends this mode early.
At the deadline, the worker deletes the torrent and its files even if peers are
downloading. This is explicit in the selection's description. Native client
time limits remain disabled to prevent unverified elapsed time from deleting
files. Conversion retains its existing original-file protection and policy.

Other modes retain the 50-hour default, ratio targets, extra hours and peer-wait
behaviour. Deletion receipts report the actual configured duration and a time
reason for minute-based downloads. No existing torrent policies are migrated.

## Verification

```sh
python -m pytest tests -q
node tests/viking_battle_model.cjs
python tests/browser_appearance.py
python tests/browser_manual_seed_minutes.py
python tests/browser_keep_seeding.py
```

Run the backend suite on Linux (production uses Linux filesystem semantics).
Browser tests cover both themes, persistent settings, responsive layouts,
pointer/keyboard defeats, paused dialogs, manual submissions and RSS exclusion.

# Fjord-konvertering til Windows

Pc-programmet med én samlet FjordSeed-visning og valg af netværksdrev.
Forbindelsen til FjordSeed bevares, mens det nye konverteringsflow bygges.

## Installation

Krav: Windows 10/11 64-bit med `tar.exe`, Python 3.13 med tkinter og Python på
PATH samt en NVIDIA-GPU og driver med HEVC/NVENC-understøttelse. Programmet er
testet på RTX 4090. Python kan hentes fra [python.org](https://www.python.org/downloads/windows/).

Download/klon repoet. Luk en eventuel åben Fjord-konvertering, og kør dette
i PowerShell fra denne mappe:

```powershell
.\install.ps1
```

Installationen henter værktøjerne fra deres officielle udgivelser, kontrollerer
SHA-256 og opretter genvejen **Fjord-konvertering** på skrivebordet. Den kræver
ikke administratorrettigheder. Programmet installeres i
`%LOCALAPPDATA%\FjordEncode`. En eventuel lokal PowerShell-politik kan kræve,
at du godkender den downloadede installationsfil, før Windows vil køre den.

Installationen bygger en almindelig `Fjord-konvertering.exe` med indlejret ikon
ved hjælp af PyInstaller 6.22.3 fra PyPI. Python kræves til installation/bygning;
den færdige EXE indeholder sin egen Python/Tk-runtime. Værktøjerne fra `tools.json`
skal fortsat ligge ved siden af EXE’en. `-SourceOnly` springer EXE-bygningen over.
EXE’er og byggede binære værktøjer lægges ikke i Git.

Genbyg EXE’en fra kildekoden med:

```powershell
python .\build_windows.py
```

Alternativ mappe og ingen skrivebordsgenvej:

```powershell
.\install.ps1 -InstallDir "$env:LOCALAPPDATA\FjordEncode-test" -NoShortcut
```

Du kan også klargøre værktøjerne manuelt efter `tools.json` og starte
`pythonw.exe fjord_encode.pyw`. De forventede stier er:

```text
NVEncC64.exe                # med alle DLL-filer fra samme arkiv
ffmpeg/bin/ffprobe.exe      # med FFmpegs øvrige bin-filer
mkvtoolnix/mkvpropedit.exe  # med resten af MKVToolNix-arkivet
```

## Programfladen

Programmet har nu én samlet visning: **FjordSeed-konvertering**.
Vælg drev i listen, f.eks. **M:\**, og brug **Opdatér drev**, hvis et nyt
netværksdrev er blevet tilsluttet. Valget gemmes uden at ændre eksisterende
forbindelsesoplysninger eller ældre konverteringspræferencer.

Dette trin ændrer kun programfladen. **Konvertér** er endnu ikke aktiv,
fordi det nye arbejdsforløb aftales separat. Programmet starter ikke den
ældre HTTP-hentning eller den lokale filkonvertering automatisk.

## Forbindelse og indstillinger

**Indstillinger** indeholder forbindelseskoden og **Start med Windows**.
Tidligere gemte forbindelsesoplysninger bevares. En ny kode erstatter adresse
og token samlet; tokenet gemmes fortsat krypteret med Windows DPAPI.
Adressen vises ikke og skal ikke indtastes manuelt.

## Baggrund og Windows-opstart

**Kør i baggrunden** og vinduets lukkeknap skjuler vinduet ved uret.
**Afslut** eller `Ctrl+Q` lukker programmet helt. Automatisk Windows-opstart
bruger fortsat `--background`, hvis brugeren har slået det til.

## Konverteringsmotor til det kommende arbejdsforløb

- NVEncC **9.39**, NVIDIA NVENC, HEVC, preset `quality`.
- Valg: **20 Mbps – spar plads**, **30 Mbps – balance (anbefalet)** og
  **40 Mbps – høj kvalitet**. Nye installationer starter på 30 Mbps.
  Maksimum/VBV er 1,5 gange den valgte bitrate (30/45/60 Mbps).
  Tidligere gemte valg og allerede oprettede FjordSeed-jobs bevares.
  Pc-jobs bruger FjordSeeds bitrate; programmets valg gælder lokale film.
- Original opløsning, billedhastighed og farver; MKV som container.
- CPU-afkodning (`--avsw`), GPU-encoding. Ingen automatisk CPU-encoding.
- Lyd, undertekster, vedhæftninger, metadata og kapitler kopieres.
- HDR10-metadata bevares. Dolby Vision 7 eller 8.1 bliver til **8.1** med RPU.
  Profil 7's ekstra billedlag følger ikke med. Andre DV-profiler afvises.
- Sporflag rettes med MKVToolNix, og bitrate-statistik genberegnes.
- Video, HDR/DV-data, varighed, lyd, undertekster og kapitler kontrolleres.

Lavere bitrate er tabsbehæftet og kan koste billeddetaljer. Bitraten er et
gennemsnitligt mål for videoen; kopieret lyd kommer oveni.

`encode_core.py` indeholder de samme `probe`, `command`, `validate` og
`restore_flags`-funktioner som serverens `converter_worker.py`. Windows-wrapperen
vælger lokale værktøjsstier og skjuler konsolvinduer. Ved ændringer til serverens
konvertering skal disse funktioner også opdateres her.

## Filer og værktøjer

- `fjord_encode.pyw`: konverteringsjob og startpunkt.
- `fjord_ui.py`: brugerflade, filvalg, fremdrift og stop.
- `windows_drop.py`: native Windows-fil-drop med Unicode-understøttelse.
- `encode_core.py`: encoderkommando og kontrol af resultatet.
- `fjord.ico`: program- og genvejsikon.
- `tools.json` / `install.ps1`: versionsfastlåste downloads og checksums.
- `remote_agent.py` / `remote_panel.py`: forbindelsen og joboverførslen til FjordSeed.
- `windows_secret.py`: tokenlagring med DPAPI.
- `windows_background.py`: ikon ved uret og beskeder med forventet tid.
- `windows_startup.py` / `windows_instance.py`: valgfri opstart og én programinstans.
- `make_icon.py`: genererer Fjord-ikonet i størrelser fra 16 til 256 pixels.

Python-koden bruger kun standardbiblioteket. Binære værktøjer downloades separat
og distribueres under deres respektive licenser:
[NVEncC](https://github.com/rigaya/NVEnc),
[FFmpeg/BtbN](https://github.com/BtbN/FFmpeg-Builds) og
[MKVToolNix](https://mkvtoolnix.download/).

`preferences.json`, videoer, logs, testfiler og downloadede værktøjer er lokale
og er udeladt fra Git. Denne mappe indgår ikke i FjordSeeds Docker-image.

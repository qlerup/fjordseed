# Fjord-konvertering til Windows

Det selvstændige pc-program med mørkt Fjord-design og NVIDIA GPU-konvertering.
Det kræver ingen FjordSeed-server eller login. Konvertering på pc'en starter
ikke konvertering i FjordSeed.

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

## Brug

1. Træk én videofil ind i vinduet, eller tryk **Vælg film**.
2. Vælg gemmemappe og eventuelt en anden video-bitrate.
3. Tryk **Start konvertering**.

Fremdriften viser procent, fps, anslået resterende tid og tid brugt.
**Stop** afbryder jobbet. **Se log** viser encoderens log, og **Åbn resultat**
åbner den færdige video i din standardafspiller.

Originalfilen bruges som input og overskrives ikke. Hvert resultat får et
unikt filnavn. Under arbejdet hedder filen `.partial.mkv`; den bliver først
omdøbt til den færdige MKV, når kontrollen består. Ved stop/fejl beholdes
ufærdig fil og log til undersøgelse. Den valgte mappe skal have mindst
originalfilens størrelse plus 1 GiB ledigt.

## Samme konvertering som FjordSeed

- NVEncC **9.39**, NVIDIA NVENC, HEVC, preset `quality`.
- Standard: **20 Mbps video**, maksimum/VBV 30 Mbps. Valg: 10/15/20/25/30 Mbps.
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

Python-koden bruger kun standardbiblioteket. Binære værktøjer downloades separat
og distribueres under deres respektive licenser:
[NVEncC](https://github.com/rigaya/NVEnc),
[FFmpeg/BtbN](https://github.com/BtbN/FFmpeg-Builds) og
[MKVToolNix](https://mkvtoolnix.download/).

`preferences.json`, videoer, logs, testfiler og downloadede værktøjer er lokale
og er udeladt fra Git. Denne mappe indgår ikke i FjordSeeds Docker-image.

# Fjord-konvertering til Windows

Pc-programmet med mørkt Fjord-design og NVIDIA GPU-konvertering. Det kan både
bruges lokalt uden login og forbindes til FjordSeed som ekstern GPU-worker.
Lokale film starter ikke et download eller konverteringsjob på serveren.

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

## Forbind til FjordSeed

Åbn **FjordSeed-forbindelse**, og indsæt serveradressen og et pc-token fra
**Indstillinger → Konvertering** i FjordSeed. Vælg lokal midlertidig plads, og
tryk **Forbind og hent jobs**. Programmet tester GPU’en, henter et job,
konverterer og returnerer resultatet. Serveren kontrollerer og publicerer filen
i biblioteket. Se [hele forløbet og API’et](../docs/pc-conversion.md).

Pc-tokenet gemmes krypteret med Windows DPAPI, aldrig som klartekst i
indstillingerne. **Forbind automatisk, når programmet åbnes** er et separat
valg. Lokal konvertering og FjordSeed-jobs deler samme GPU-lås, så de ikke
starter samtidig i samme program.

## Baggrund, beskeder og Windows-opstart

- **Kør i baggrunden** og vinduets lukkeknap skjuler vinduet ved uret.
  Konverteringer og FjordSeed-forbindelsen fortsætter.
- Klik på Fjord-ikonet ved uret for at åbne igen. Højreklik giver **Åbn** og
  **Afslut**. Windows kan placere ikonet under pilen med skjulte ikoner.
- **Afslut** eller `Ctrl+Q` lukker programmet. Stop først et aktivt job.
- Når en film begynder at blive konverteret, vises filnavnet i en lille besked
  nederst til højre. Estimeret resterende tid opdateres, når encoderen leverer
  de første målinger. Beskeden tager ikke tastaturfokus og forsvinder automatisk.
- **Start med Windows** tilføjer/fjerner programmets egen HKCU Run-værdi for
  den aktuelle bruger. Det kræver ikke administratorrettigheder og er slået fra
  som udgangspunkt. Automatisk opstart bruger `--background`.
- Programmet kører kun én gang pr. installation; en ny åbning viser det
  eksisterende vindue. Det har sit eget Fjord-ikon og AppUserModelID, så det
  grupperes separat fra Python på proceslinjen.

## Samme konvertering som FjordSeed

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

# Fjord-konvertering til Windows

Pc-programmet med én samlet FjordSeed-visning og valg af netværksdrev.
Forbindelsen til FjordSeed bevares, mens det nye konverteringsflow bygges.

## Installation til Windows

Hent **Fjord-konvertering-Setup.exe** under **Indstillinger → Konvertering**
i FjordSeed eller fra [seneste Windows-udgivelse](https://github.com/qlerup/fjordseed/releases/latest).
Installationspakken indeholder programmet og videoværktøjerne; Python skal
ikke installeres på pc’en. Den opretter en startmenugenvej og tilbyder en
skrivebordsgenvej. Afinstallation findes under Windows’ installerede apps.
Brugerens egne forbindelsesoplysninger og præferencer bliver ikke pakket med
og bevares ved opdatering og afinstallation.

## Udviklerinstallation fra kildekode

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
Tryk **Vælg mappe…** for at åbne Windows' mappevælger. Vælg f.eks. en
mappe på **M:** eller en tilgængelig netværksmappe. Valget gemmes uden at
ændre eksisterende forbindelsesoplysninger eller konverteringspræferencer.
Den valgte sti deles automatisk med FjordSeed via pc'ens tokenforbindelse,
ved opstart og efter ændringer. Ved forbindelsesfejl prøves igen. Stien vises
under den tilsluttede pc i FjordSeeds konverteringsindstillinger; den behandles
som en Windows-sti og bruges ikke som en servermappe.
Pc'en sender også en begrænset oversigt over videofilernes relative navne og
størrelser. FjordSeed viser dem i mapper med søgning. Uden valgt mappe vises
en ventebesked og ingen filliste. Skjulte arbejdsmapper og Seeder udelades.
Færdigkonverterede filer skjules automatisk i arbejdslisten. I FjordSeed kan
du springe en fil, en genkendt serie eller en hel mappe over og medtage dem
igen med **Vis sprunget over**. Valgene gemmes for pc'en og dens valgte mappe;
mediefiler flyttes eller slettes ikke af disse valg.
FjordSeed viser videobitrate og filens samlede gennemsnitsbitrate. Mapper
viser spændet i videobitrate for deres filer. Oplysningerne indlæses fra
serverens filer i små portioner og caches, så de ikke skal probes ved hvert
heartbeat. Ukendte værdier vises som ukendte.

**Send til pc** starter automatisk GPU-konverteringen med 20, 30 eller 40 Mbps
fra FjordSeed. Pc'en læser originalfilen direkte fra netværksdrevet og skriver
resultatet under `.fjordseed-shared/<job-id>` i samme netværksmappe. Der er ingen
første download til pc'ens cache og ingen upload af en hel færdig film.

Efter pc'ens kontrol giver den besked via tokenforbindelsen. Serveren kontrollerer
resultatet igen og beder qBittorrent flytte hele torrentens oprindelige struktur
til Seeder. Først derefter publiceres filmen på bibliotekets normale plads.
Undertekster og øvrige ledsagefiler bevares; undertekster kopieres uafhængigt,
så en ændring i biblioteket ikke ændrer torrentens original. Ved flere afsnit i
samme torrent flyttes originalpakken én gang; senere afsnit erstattes i biblioteket.
**Afbryd konvertering** stopper en igangværende encoding og bevarer originalerne.

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

## Byg installationspakken

Installer Inno Setup 6.7.3 fra den officielle udgivelse, og kør på Windows:

```powershell
python build_installer.py --compiler "C:/path/to/ISCC.exe" --archives "C:/path/to/archive-cache" --output-dir dist
```

Bygningen bruger kun den nye EXE og checksum-kontrollerede leverandørarkiver,
ikke indholdet af en eksisterende brugerinstallation. SHA-256 for den færdige
installer gemmes ved siden af filen. GitHub-workflowet **Windows installer**
kan bygge og udgive en ny version manuelt. Brug et nyt versionsnummer ved
hver udgivelse. Den seneste udgivelse er downloadmålet i FjordSeed.

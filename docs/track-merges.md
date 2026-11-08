# Flet spor fra to filer

Under **Indstillinger → Konvertering → Flet spor fra to filer** vælges først hovedfilen, som leverer video og kapitler. Vælg derefter en anden filmfil, som leverer ekstra lydspor og indbyggede undertekster. Alle hovedfilens lydspor og undertekster er valgt fra start; ingen donorspor er valgt. Afkryds præcis de spor, resultatet skal indeholde.

MKVToolNix kopierer sporene uden genkodning. Eksempelvis kan et E-AC-3 JOC-spor eller TrueHD Atmos-spor tilføjes til en anden udgave uden at konvertere lyden. Lydsprog, spornavne, forced-markeringer, hovedfilens kapitler og vedhæftninger bevares. Donorens vedhæftninger kopieres også ved import af undertekster, så skrifttyper til ASS/SSA følger med. Donorens video og kapitler importeres ikke. Donorspor sættes ikke som standardspor, så de ikke konkurrerer med hovedfilens standardvalg.

Resultatet får navnet `<hovedfil>.merged-<job-id>.mkv` ved siden af hovedfilen. Begge originaler bevares, og deres torrentindhold ændres ikke. Resultatet bliver en separat biblioteksfil. Ingen GPU eller pc-konverter kræves; arbejdet udføres i serverens qBittorrent-container, hvor MKVToolNix allerede er installeret.

## Timing

Vælg samme klipning af filmen. Forskellig varighed udløser en advarsel. En valgfri forskydning i hele millisekunder gælder alle valgte spor fra donorfilen: `1000` forsinker dem ét sekund; `-1000` fremrykker dem ét sekund. Klippeforskelle og drift på grund af forskellige billedhastigheder korrigeres ikke automatisk. Separate SRT/SUP-filer er ikke en del af dette valg; menuen viser spor indbygget i de to filmfiler.

## Kø og fejl

Flettekøen behandler ét job ad gangen og viser MKVToolNix' målte fremdrift. Køen tillader højst 100 ventende/aktive jobs. Ventende og fejlede jobs kan fjernes; fejlede jobs kan forsøges igen, hvis kildefilerne stadig matcher valget. Kø og jobhandlinger er knyttet til den indloggede bruger.

Filerne valideres ved køoprettelse, før arbejdet og igen før publicering. Resultatets spor kontrolleres mod valget. Resultatet publiceres atomisk uden overskrivning; skjulte arbejdsfiler indgår ikke i bibliotekets videoliste. Ved afbrudt worker frigiver operativsystemet arbejdslåsen. Jobbet markeres til kontrol, og en afbrudt publicering kan genoptages, når arbejdskopien og resultatet er samme fil. Diskpladskontrollen reserverer konservativt plads svarende til begge kildefiler plus 256 MiB; der reserveres ikke faktisk diskplads.

Web-API: `/api/merge/library`, `/api/merge/library/<id>`, `/api/merge/jobs`, `/api/merge/queue` og `/api/merge/jobs/<id>/{cancel,retry}`. Stier vælges fra serverens eksisterende bibliotek; browseren sender fil-id'er, præcise fingeraftryk og MKVToolNix-spor-id'er.

## Verifikation

`python -m pytest tests/test_merge_media.py -q` dækker sporvalg, forældede kilder, kø, isolation, fejlet fletning, publiceringskollisioner og genstart. Med MKVToolNix og FFmpeg kører også en rigtig fletning med byte-identisk H.264-video og E-AC-3-lyd samt kontrol af underteksttiming, sprog og forced-markeringer. `python tests/browser_merge_tracks.py` kontrollerer flow og fejl i Fjord- og Nordic-tema ved 1440, 390 og 320 pixels.

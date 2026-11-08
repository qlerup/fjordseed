# Flet spor fra to filer

Under **Indstillinger → Konvertering → Flet spor fra to filer** vælges først hovedfilen, som leverer video og kapitler. Vælg derefter en anden filmfil, som leverer ekstra lydspor og indbyggede undertekster. Alle hovedfilens lydspor og undertekster er valgt fra start; ingen donorspor er valgt. Afkryds præcis de spor, resultatet skal indeholde.

MKVToolNix kopierer sporene uden genkodning. Eksempelvis kan et E-AC-3 JOC-spor eller TrueHD Atmos-spor tilføjes til en anden udgave uden at konvertere lyden. Lydsprog, spornavne, forced-markeringer, hovedfilens kapitler og vedhæftninger bevares. Donorens vedhæftninger kopieres også ved import af undertekster, så skrifttyper til ASS/SSA følger med. Donorens video og kapitler importeres ikke. Donorspor sættes ikke som standardspor, så de ikke konkurrerer med hovedfilens standardvalg.

Resultatet får navnet `<hovedfil>.merged-<job-id>.mkv` ved siden af hovedfilen. Begge originaler bevares, og deres torrentindhold ændres ikke. Resultatet bliver en separat biblioteksfil. Ingen GPU eller pc-konverter kræves; arbejdet udføres i serverens qBittorrent-container, hvor MKVToolNix allerede er installeret.

## Timing

Vælg samme klipning af filmen. Forskellig varighed udløser en advarsel. En valgfri forskydning i hele millisekunder gælder alle valgte spor fra donorfilen: `1000` forsinker dem ét sekund; `-1000` fremrykker dem ét sekund. Klippeforskelle og drift på grund af forskellige billedhastigheder korrigeres ikke automatisk. Separate SRT/SUP-filer er ikke en del af dette valg; menuen viser spor indbygget i de to filmfiler.

### Automatisk lydmatch og prøveklip

Vælg et reference-lydspor fra hver film, helst samme sprog, og tryk **Find forskydning automatisk**. Sammenligningssporene behøver ikke begge at blive beholdt i den færdige film. Serveren udtrækker mono-lyd ved 4 kHz fra tre steder i hovedfilen (12 %, 50 % og 85 %). For hvert sted søges efter samme lyd op til 120 sekunder før og efter den nuværende forskydning. FFT-baseret normaliseret krydskorrelation finder de matchende signaler, også ved forskellig lydstyrke eller omvendt polaritet.

Stilhed og ikke-entydige gentagelser giver ikke et sikkert forslag. Mindst to forskellige steder skal have et stærkt, entydigt match og være enige inden for 40 ms. Hvis stærke matches giver forskellige forskydninger, markeres ændret timing/klipning, og knappen til at anvende én forskydning vises ikke. Matchscore er signalets korrelation, ikke en sandsynlighed for korrekt synkronisering. Forslaget er et estimat, som bør kontrolleres med video; det garanterer ikke, at alle andre lydsprog og undertekster har samme timing.

Grafen lægger de normaliserede lydkurver oven på hinanden og følger den valgte forskydning. **Brug … ms** overfører et sikkert forslag til fletningens eksisterende felt. Knapperne til 10/100/1000 ms og skyderen kan finjustere det uden at flette en ny film.

**Lav 15 sek. prøveklip** opretter små H.264/AAC-kopier fra et valgfrit tidspunkt i filmen. Hovedfilens billede kan afspilles med donorens lyd; donorens billede vises ved siden af, så scene-/klippeforskelle kan ses. Lydkilden kan skiftes under afspilning. Donorprøven har fem sekunders margin før den forventede position; større justeringer kan kræve et nyt kort prøveklip. Det færdige resultat bruger stadig de originale spor, inklusive Atmos/JOC. Undertekster vises ikke i prøveklippene. HDR-prøver tone-mappes til SDR til browseren.

Prøvernes tidsstempler bevares under udtræk og trimmes til den præcise prøveposition. Det undgår hele codec-frame-fejl ved forskellige starttider eller delvise AC-3/E-AC-3-pakker. Analyse og prøveklip kører i en separat baggrundskø uden at oprette et flettejob eller ændre kildefilerne. Én kontrol pr. bruger kan vente/køre ad gangen, og filer fra afsluttede kontroller ryddes efter en time. Medieadgang er beskyttet af samme login og ejerskab som kontrollen og understøtter HTTP byte ranges til videoseeking.

API: `POST /api/merge/checks` (`kind: analyse|preview`), `GET /api/merge/checks/<id>` og `GET /api/merge/checks/<id>/{base,donor}.mp4`.

## Kø og fejl

Flettekøen behandler ét job ad gangen og viser MKVToolNix' målte fremdrift. Køen tillader højst 100 ventende/aktive jobs. Ventende og fejlede jobs kan fjernes; fejlede jobs kan forsøges igen, hvis kildefilerne stadig matcher valget. Kø og jobhandlinger er knyttet til den indloggede bruger.

Filerne valideres ved køoprettelse, før arbejdet og igen før publicering. Resultatets spor kontrolleres mod valget. Resultatet publiceres atomisk uden overskrivning; skjulte arbejdsfiler indgår ikke i bibliotekets videoliste. Ved afbrudt worker frigiver operativsystemet arbejdslåsen. Jobbet markeres til kontrol, og en afbrudt publicering kan genoptages, når arbejdskopien og resultatet er samme fil. Diskpladskontrollen reserverer konservativt plads svarende til begge kildefiler plus 256 MiB; der reserveres ikke faktisk diskplads.

Web-API: `/api/merge/library`, `/api/merge/library/<id>`, `/api/merge/jobs`, `/api/merge/queue` og `/api/merge/jobs/<id>/{cancel,retry}`. Stier vælges fra serverens eksisterende bibliotek; browseren sender fil-id'er, præcise fingeraftryk og MKVToolNix-spor-id'er.

## Verifikation

`python -m pytest tests/test_merge_media.py -q` dækker sporvalg, forældede kilder, kø, isolation, fejlet fletning, publiceringskollisioner og genstart. Med MKVToolNix og FFmpeg kører også en rigtig fletning med byte-identisk H.264-video og E-AC-3-lyd samt kontrol af underteksttiming, sprog og forced-markeringer. `python tests/browser_merge_tracks.py` kontrollerer flow og fejl i Fjord- og Nordic-tema ved 1440, 390 og 320 pixels.

`python -m pytest tests/test_merge_sync.py -q` kontrollerer fortegn og millisekundmatch, gain/støj/polaritet, stilhed, gentagelser, drift, ændrede kilder, ejerskab og videoranges. En rigtig AC-3/E-AC-3-prøve med en kendt forskydning på 437 ms kontrollerer både analysen og de resulterende AAC-prøveklips timing. `python tests/browser_merge_sync.py` tester graf, forskydningsfelt, lydskift, afspilning, fejl og drift i begge temaer ved 1440, 390 og 320 pixels. Workflowet **Track merging and audio sync** kører de nye backend- og browsertests på GitHub Actions.
